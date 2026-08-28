"""Tests for sector-6 InfoCuria-then-CELLAR supplementation.

InfoCuria's ``documents.searchHits`` array only carries a couple of
language variants for most cases — typically the procedural language plus
EN. CELLAR's ``expression_uses_language`` graph carries all 23 EU-official
languages for the same work.

After this change, sector 6 always supplements InfoCuria's fulltexts with
CELLAR's manifestation graph (unconditionally — not env-var gated), so the
``fulltexts`` list contains every language CELLAR has, with InfoCuria's
entries kept verbatim where both sources have the same language.
"""

from __future__ import annotations

import pytest

from cellar_extractor import eurlex_scraping

# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------


def _make_infocuria_response(doc_langs):
    """Build a fake InfoCuria /procedures response with N docLang variants."""
    return {
        "searchHits": [
            {
                "content": {
                    "matCodeML": [{"label": [{"en": "Test subject"}]}],
                    "matCode": ["TEST"],
                    "advocateML": [],
                    "avg": "",
                    "reportingJudgeML": [],
                    "reportingJudge": "",
                    "joinAffairs": [],
                    "procedureResultTypeML": [],
                    "parties": "",
                },
                "innerHits": {
                    "document": {
                        "searchHits": [
                            {
                                "content": {
                                    "docLang": lang,
                                    "docFormats": ["HTML"],
                                    "logicDocId": "id_1",
                                    "idProcedure": "C/0001/24/00000000RP/01/P/01",
                                    "docTypeCode": "ARRET",
                                }
                            }
                            for lang in doc_langs
                        ]
                    }
                },
            }
        ]
    }


def _patch_infocuria(monkeypatch, doc_langs):
    """Stub InfoCuria endpoints to return success with the given doc_langs."""

    def _post(url, payload, retries=3):
        if url.endswith("/suggest"):
            return [
                {
                    "procedureDocInfo": {
                        "id": "C/0001/24/00000000RP/01/P/01-999",
                        "idPublished": "C-1/24",
                    }
                }
            ]
        if url.endswith("/affairId/procedures"):
            return _make_infocuria_response(doc_langs)
        return None

    class _Resp:
        status_code = 200

        def __init__(self, lang):
            self.text = f"<html>infocuria body in {lang}</html>"

    class _Session:
        def get(self, url, timeout=60):
            for lang in doc_langs:
                if f"-{lang}-1.html" in url:
                    return _Resp(lang)
            # fallback for the primary fetch with the InfoCuria-only flow
            return _Resp("UNK")

    monkeypatch.setattr(eurlex_scraping, "_post_json", _post)
    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _Session())


def _patch_cellar(monkeypatch, languages, work_uri=None):
    """Stub the CELLAR side to return one manifestation per language."""
    if work_uri is None:
        work_uri = "http://publications.europa.eu/resource/cellar/test-uuid"

    items = [
        {
            "item_url": f"http://cellar/{lang}",
            "format": "xhtml",
            "language": lang,
        }
        for lang in languages
    ]

    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uri",
        lambda celex, sector="8": work_uri,
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uris",
        lambda celex, sector="8": [work_uri] if work_uri else [],
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_items_for_work",
        lambda uri: items,
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_subject_labels",
        lambda uri, language="en": ["CELLAR-subject"],
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_extract_item_payload",
        lambda url, fmt: (f"cellar body for {url}", "", fmt),
    )


# ---------------------------------------------------------------------------
# Behaviour tests
# ---------------------------------------------------------------------------


def test_infocuria_success_is_supplemented_with_cellar_languages(monkeypatch):
    """InfoCuria gave us EN+FR; CELLAR has those plus 5 more languages.
    The final fulltexts list should contain all 7."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _patch_infocuria(monkeypatch, doc_langs=["EN", "FR"])
    _patch_cellar(monkeypatch, languages=["EN", "FR", "DE", "IT", "NL", "ES", "PT"])

    data = eurlex_scraping._get_case_data_sector6("62024CJ0001", language="EN")

    assert data is not None
    langs = {entry["text_language"] for entry in data["fulltexts"]}
    assert langs == {"EN", "FR", "DE", "IT", "NL", "ES", "PT"}


def test_infocuria_entries_are_preserved_when_languages_overlap(monkeypatch):
    """When both sources have the same language, keep InfoCuria's entry —
    it's the court's own publication and typically has higher fidelity."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _patch_infocuria(monkeypatch, doc_langs=["EN", "FR"])
    _patch_cellar(monkeypatch, languages=["EN", "FR", "DE"])

    data = eurlex_scraping._get_case_data_sector6("62024CJ0001", language="EN")

    by_lang = {entry["text_language"]: entry for entry in data["fulltexts"]}
    # The EN + FR entries should still be from InfoCuria.
    assert by_lang["EN"]["text_source"] == "INFOCURIA_BLOB_HTML"
    assert "infocuria body in EN" in by_lang["EN"]["text"]
    assert by_lang["FR"]["text_source"] == "INFOCURIA_BLOB_HTML"
    assert "infocuria body in FR" in by_lang["FR"]["text"]
    # DE only existed in CELLAR — comes through with CELLAR_ITEM source.
    assert by_lang["DE"]["text_source"] == "CELLAR_ITEM"
    assert "cellar body" in by_lang["DE"]["text"]


def test_metadata_fields_remain_from_infocuria_even_when_cellar_supplements(monkeypatch):
    """The judge / advocate / directory_codes etc. come from InfoCuria —
    CELLAR can't populate those. After supplementation those fields
    should still reflect InfoCuria's response, not be overwritten."""
    eurlex_scraping._get_case_data_cached.cache_clear()

    def _post(url, payload, retries=3):
        if url.endswith("/suggest"):
            return [
                {
                    "procedureDocInfo": {
                        "id": "C/0001/24/00000000RP/01/P/01-999",
                        "idPublished": "C-1/24",
                    }
                }
            ]
        if url.endswith("/affairId/procedures"):
            return {
                "searchHits": [
                    {
                        "content": {
                            "matCodeML": [{"label": [{"en": "Environment"}]}],
                            "matCode": ["ENVI"],
                            "advocateML": [{"code": "KOK", "label": [{"en": "Kokott"}]}],
                            "avg": "KOK",
                            "reportingJudgeML": [
                                {"code": "SGE", "label": [{"en": "Spielmann"}]}
                            ],
                            "reportingJudge": "SGE",
                            "joinAffairs": ["C-2/20"],
                            "procedureResultTypeML": [{"label": [{"en": "Judgment"}]}],
                            "parties": "Party A",
                        },
                        "innerHits": {
                            "document": {
                                "searchHits": [
                                    {
                                        "content": {
                                            "docLang": "EN",
                                            "docFormats": ["HTML"],
                                            "logicDocId": "id_1",
                                            "idProcedure": "C/0001/24/00000000RP/01/P/01",
                                            "docTypeCode": "ARRET",
                                        }
                                    },
                                ]
                            }
                        },
                    }
                ]
            }
        return None

    class _Resp:
        status_code = 200
        text = "<html>en body</html>"

    class _Session:
        def get(self, url, timeout=60):
            return _Resp()

    monkeypatch.setattr(eurlex_scraping, "_post_json", _post)
    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _Session())
    _patch_cellar(monkeypatch, languages=["DE", "IT"])

    data = eurlex_scraping._get_case_data_sector6("62024CJ0001", language="EN")

    # Metadata still from InfoCuria
    assert data["advocate"] == "Kokott"
    assert data["judge"] == "Spielmann"
    assert data["directory_codes"] == "ENVI"
    # Keywords come from InfoCuria (CELLAR's subject label NOT merged into top-level
    # keywords — to keep the existing schema stable across modern + ancient cases).
    assert "Environment" in data["keywords"]


def test_supplementation_is_noop_when_cellar_has_nothing_extra(monkeypatch):
    """If CELLAR returns no new languages, the fulltexts list is unchanged
    and the metadata is untouched. Belt-and-braces idempotency."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _patch_infocuria(monkeypatch, doc_langs=["EN", "FR", "DE"])
    _patch_cellar(monkeypatch, languages=["EN", "FR", "DE"])  # exact overlap

    data = eurlex_scraping._get_case_data_sector6("62024CJ0001", language="EN")

    langs = sorted(entry["text_language"] for entry in data["fulltexts"])
    assert langs == ["DE", "EN", "FR"]
    # No CELLAR_ITEM entries — every language already had an InfoCuria source.
    sources = {entry["text_source"] for entry in data["fulltexts"]}
    assert sources == {"INFOCURIA_BLOB_HTML"}


def test_supplementation_skips_when_cellar_work_uri_unresolvable(monkeypatch):
    """If CELLAR can't find the work URI (some pre-CELLAR cases), the
    supplementation step quietly noops and InfoCuria's results stand."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _patch_infocuria(monkeypatch, doc_langs=["EN", "FR"])
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uri",
        lambda celex, sector="8": "",
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uris",
        lambda celex, sector="8": [],
    )

    data = eurlex_scraping._get_case_data_sector6("62024CJ0001", language="EN")

    assert data is not None
    langs = sorted(entry["text_language"] for entry in data["fulltexts"])
    assert langs == ["EN", "FR"]


def test_supplementation_skips_failed_cellar_payload_extracts(monkeypatch):
    """CELLAR may list a manifestation whose item URL returns nothing.
    Those rows must NOT pollute the fulltexts list."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _patch_infocuria(monkeypatch, doc_langs=["EN"])

    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uri",
        lambda celex, sector="8": "http://cellar/uri",
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uris",
        lambda celex, sector="8": ["http://cellar/uri"],
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_items_for_work",
        lambda uri: [
            {"item_url": "http://cellar/de", "format": "xhtml", "language": "DE"},
            {"item_url": "http://cellar/it", "format": "xhtml", "language": "IT"},
        ],
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_subject_labels",
        lambda uri, language="en": [],
    )

    def _fake_extract(url, fmt):
        # DE comes through, IT returns empty
        if "/de" in url:
            return ("german body", "", fmt)
        return ("", "", "")

    monkeypatch.setattr(eurlex_scraping, "_extract_item_payload", _fake_extract)

    data = eurlex_scraping._get_case_data_sector6("62024CJ0001", language="EN")

    langs = sorted(entry["text_language"] for entry in data["fulltexts"])
    assert langs == ["DE", "EN"]  # IT dropped because the extract was empty
