"""Tests for multi-language fulltext fanout.

The pipeline historically fetched ONE language per ECLI (always EN). CJEU
publishes in all 23 EU languages — these tests assert the new behaviour:
the sector handlers return a ``fulltexts`` list with one record per
available language, and ``fulltext_saving.execute_sections_threads`` emits
one JSON row per (CELEX, language).
"""

from __future__ import annotations

import pandas as pd

from cellar_extractor import eurlex_scraping, fulltext_saving

# ---------------------------------------------------------------------------
# _choose_best_per_language helper
# ---------------------------------------------------------------------------


def test_choose_best_per_language_returns_one_record_per_language():
    """Same language with 3 formats (xhtml > html > pdf) → best wins per lang."""
    candidates = [
        {"item_url": "u_en_xhtml", "format": "xhtml", "language": "EN"},
        {"item_url": "u_en_pdf", "format": "pdf", "language": "EN"},
        {"item_url": "u_fr_html", "format": "html", "language": "FR"},
        {"item_url": "u_fr_pdf", "format": "pdf", "language": "FR"},
        {"item_url": "u_it_pdf", "format": "pdf", "language": "IT"},
    ]
    out = eurlex_scraping._choose_best_per_language(candidates, summary=False)
    by_lang = {c["language"]: c for c in out}
    assert by_lang["EN"]["item_url"] == "u_en_xhtml"  # xhtml beats pdf
    assert by_lang["FR"]["item_url"] == "u_fr_html"  # html beats pdf
    assert by_lang["IT"]["item_url"] == "u_it_pdf"
    assert len(out) == 3


def test_choose_best_per_language_skips_unknown_formats():
    """Candidates with formats outside SECTOR8_MAIN_FORMAT_ORDER are dropped."""
    candidates = [
        {"item_url": "u1", "format": "xhtml", "language": "EN"},
        {"item_url": "u2", "format": "junk_format", "language": "DE"},
    ]
    out = eurlex_scraping._choose_best_per_language(candidates, summary=False)
    assert len(out) == 1
    assert out[0]["language"] == "EN"


def test_choose_best_per_language_groups_empty_language_separately():
    """Candidates without a language tag are bucketed under '' rather than
    dropped — some manifestations lack expression_uses_language."""
    candidates = [
        {"item_url": "u_no_lang_xhtml", "format": "xhtml", "language": ""},
        {"item_url": "u_no_lang_pdf", "format": "pdf", "language": ""},
        {"item_url": "u_en", "format": "xhtml", "language": "EN"},
    ]
    out = eurlex_scraping._choose_best_per_language(candidates, summary=False)
    by_lang = {c["language"]: c for c in out}
    assert by_lang[""]["item_url"] == "u_no_lang_xhtml"
    assert by_lang["EN"]["item_url"] == "u_en"


def test_choose_best_per_language_empty_input_returns_empty_list():
    assert eurlex_scraping._choose_best_per_language([], summary=False) == []


# ---------------------------------------------------------------------------
# Sector 6 InfoCuria — multi-language fanout from docLang variants
# ---------------------------------------------------------------------------


def test_sector6_infocuria_returns_fulltexts_list_with_all_languages(monkeypatch):
    """InfoCuria's `documents.searchHits` array contains every docLang
    variant. The handler should fetch the HTML blob for each language and
    return them all under `fulltexts`."""
    eurlex_scraping._get_case_data_cached.cache_clear()

    def _fake_post(url, payload, retries=3):
        if url.endswith("/suggest"):
            return [
                {
                    "procedureDocInfo": {
                        "id": "C/0131/24/00000000RP/01/P/01-999",
                        "idPublished": "C-131/24",
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
                                            "docLang": "EN",
                                            "docFormats": ["HTML"],
                                            "logicDocId": "id_1",
                                            "idProcedure": "C/0131/24/00000000RP/01/P/01",
                                            "docTypeCode": "ARRET",
                                        }
                                    },
                                    {
                                        "content": {
                                            "docLang": "FR",
                                            "docFormats": ["HTML"],
                                            "logicDocId": "id_1",
                                            "idProcedure": "C/0131/24/00000000RP/01/P/01",
                                            "docTypeCode": "ARRET",
                                        }
                                    },
                                    {
                                        "content": {
                                            "docLang": "DE",
                                            "docFormats": ["HTML"],
                                            "logicDocId": "id_1",
                                            "idProcedure": "C/0131/24/00000000RP/01/P/01",
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

    fetched_langs = []

    class _Resp:
        status_code = 200

        # text varies by language so we can assert per-language bodies were stored
        def __init__(self, lang):
            self.text = f"<html>body in {lang}</html>"

    class _Session:
        def get(self, url, timeout=60):
            # InfoCuria URL pattern embeds the docLang in the file_name part
            # of the blob URL (`...{logic_doc_id}-{doc_lang}-1.html`).
            for lang in ("EN", "FR", "DE"):
                if f"-{lang}-1.html" in url:
                    fetched_langs.append(lang)
                    return _Resp(lang)
            return _Resp("UNK")

    monkeypatch.setattr(eurlex_scraping, "_post_json", _fake_post)
    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _Session())

    data = eurlex_scraping._get_case_data_sector6("62024CJ0131", language="EN")

    assert data is not None
    assert "fulltexts" in data, "handler must expose a `fulltexts` list"
    by_lang = {entry["text_language"]: entry for entry in data["fulltexts"]}
    assert set(by_lang) == {"EN", "FR", "DE"}, f"got: {set(by_lang)}"
    assert "body in EN" in by_lang["EN"]["text"]
    assert "body in FR" in by_lang["FR"]["text"]
    assert "body in DE" in by_lang["DE"]["text"]
    # Each entry has the provenance fields populated
    for entry in data["fulltexts"]:
        assert entry["text_source"] == "INFOCURIA_BLOB_HTML"
        assert entry["text_format"] == "html"
    # Verified all three language blobs were fetched
    assert sorted(fetched_langs) == ["DE", "EN", "FR"]


# ---------------------------------------------------------------------------
# Sector 8 CELLAR — multi-language fanout from manifestation expressions
# ---------------------------------------------------------------------------


def test_sector8_returns_fulltexts_for_every_available_language(monkeypatch):
    """The CELLAR manifestation graph returns 23 expressions per work.
    The handler must fetch and return one entry per language (after
    picking the best format within each)."""
    work_uri = "http://publications.europa.eu/resource/cellar/multilang-test"
    items = [
        {"item_url": "u_en", "format": "xhtml", "language": "EN"},
        {"item_url": "u_fr", "format": "xhtml", "language": "FR"},
        {"item_url": "u_it", "format": "html", "language": "IT"},
        {"item_url": "u_nl_pdf", "format": "pdf", "language": "NL"},
        # A duplicate-format candidate for EN — should NOT add a second EN entry
        {"item_url": "u_en_html", "format": "html", "language": "EN"},
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
        lambda uri, language="en": ["Subject"],
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_summary_work_uris",
        lambda uri: [],
    )

    def _fake_extract(item_url, fmt):
        return (f"body for {item_url} ({fmt})", f"<html>{item_url}</html>", fmt)

    monkeypatch.setattr(eurlex_scraping, "_extract_item_payload", _fake_extract)

    data = eurlex_scraping._get_case_data_sector8("82023XX0001", language="EN")

    assert "fulltexts" in data
    by_lang = {e["text_language"]: e for e in data["fulltexts"]}
    assert set(by_lang) == {"EN", "FR", "IT", "NL"}
    # EN xhtml chosen over EN html (format precedence)
    assert "u_en" in by_lang["EN"]["text"] and "xhtml" in by_lang["EN"]["text"]


# ---------------------------------------------------------------------------
# Sector 6 CELLAR fallback — multi-language for pre-2001 cases too
# ---------------------------------------------------------------------------


def test_sector6_cellar_fallback_returns_all_languages(monkeypatch):
    """When falling back to CELLAR, fan out across languages just like
    sector 8 does."""
    work_uri = "http://publications.europa.eu/resource/cellar/costa"
    items = [
        {"item_url": "u_en", "format": "xhtml", "language": "EN"},
        {"item_url": "u_it", "format": "xhtml", "language": "IT"},
        {"item_url": "u_fr", "format": "html", "language": "FR"},
    ]
    monkeypatch.setattr(eurlex_scraping, "_post_json", lambda url, payload, retries=3: [])
    monkeypatch.setattr(
        eurlex_scraping, "_fetch_sector8_work_uri", lambda celex, sector="8": work_uri
    )
    monkeypatch.setattr(
        eurlex_scraping, "_fetch_sector8_items_for_work", lambda uri: items
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_subject_labels",
        lambda uri, language="en": ["Free movement of goods"],
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_extract_item_payload",
        lambda url, fmt: (f"body {url}", "", fmt),
    )

    data = eurlex_scraping._get_case_data_sector6("61964CJ0006", language="EN")

    assert data is not None
    by_lang = {e["text_language"]: e for e in data["fulltexts"]}
    assert {"EN", "IT", "FR"}.issubset(by_lang)
    for entry in data["fulltexts"]:
        assert entry["text_source"] == "CELLAR_ITEM"


# ---------------------------------------------------------------------------
# fulltext_saving — emits one JSON row per (CELEX, language)
# ---------------------------------------------------------------------------


def test_build_fulltext_records_emits_one_row_per_language():
    """When infocuria_data carries a `fulltexts` list (the new multi-language
    shape), the helper should emit one JSON-shaped dict per language with
    the celex / ecli / missing_reasons stamped on each row."""
    infocuria_data = {
        "text": "EN body",
        "text_source": "INFOCURIA_BLOB_HTML",
        "text_language": "EN",
        "text_format": "html",
        "fulltexts": [
            {
                "text": "EN body",
                "text_source": "INFOCURIA_BLOB_HTML",
                "text_language": "EN",
                "text_format": "html",
            },
            {
                "text": "FR corps de l'arrêt",
                "text_source": "INFOCURIA_BLOB_HTML",
                "text_language": "FR",
                "text_format": "html",
            },
            {
                "text": "DE Urteil",
                "text_source": "INFOCURIA_BLOB_HTML",
                "text_language": "DE",
                "text_format": "html",
            },
        ],
    }

    records = fulltext_saving._build_fulltext_records(
        infocuria_data,
        celex="62020CJ0001",
        ecli="ECLI:EU:C:2020:1",
        missing_reasons_value="",
    )

    by_lang = {r["text_language"]: r for r in records}
    assert set(by_lang) == {"EN", "FR", "DE"}
    for r in records:
        assert r["celex"] == "62020CJ0001"
        assert r["ecli"] == "ECLI:EU:C:2020:1"
        assert r["text_source"] == "INFOCURIA_BLOB_HTML"
    assert "corps de l'arrêt" in by_lang["FR"]["text"]


def test_build_fulltext_records_normalizes_composite_celex():
    """Full-text rows must use the same canonical CELEX as case loaders."""
    records = fulltext_saving._build_fulltext_records(
        {
            "fulltexts": [
                {
                    "text": "Nederlandse tekst",
                    "text_source": "INFOCURIA_BLOB_HTML",
                    "text_language": "NL",
                    "text_format": "html",
                }
            ]
        },
        celex="62025TJ0267;62025TJ0267_INF",
        ecli="ECLI:EU:T:2026:366",
        missing_reasons_value="",
    )

    assert records == [
        {
            "celex": "62025TJ0267",
            "ecli": "ECLI:EU:T:2026:366",
            "text": "Nederlandse tekst",
            "text_source": "INFOCURIA_BLOB_HTML",
            "text_language": "NL",
            "text_format": "html",
            "missing_reasons": "",
        }
    ]
def test_build_fulltext_records_falls_back_to_single_when_no_fulltexts_list():
    """Backwards-compat: legacy infocuria_data dicts that don't carry a
    `fulltexts` list (e.g. from a plug-in or stub) still produce exactly
    one row using the top-level text fields."""
    infocuria_data = {
        "text": "single body",
        "text_source": "INFOCURIA_BLOB_HTML",
        "text_language": "EN",
        "text_format": "html",
        # NB: no `fulltexts` key
    }
    records = fulltext_saving._build_fulltext_records(
        infocuria_data,
        celex="62020CJ0001",
        ecli="ECLI:EU:C:2020:1",
        missing_reasons_value="",
    )
    assert len(records) == 1
    assert records[0]["text"] == "single body"
    assert records[0]["text_language"] == "EN"


def test_build_fulltext_records_attaches_missing_reasons_to_every_row():
    """When upstream had nothing, every per-language row carries the same
    missing_reasons string — downstream tooling joins on it."""
    infocuria_data = {
        "text": "",
        "fulltexts": [],  # empty fanout (no language data at all)
    }
    records = fulltext_saving._build_fulltext_records(
        infocuria_data,
        celex="61964CJ0006",
        ecli="ECLI:EU:C:1964:6",
        missing_reasons_value="FULLTEXT_UNAVAILABLE_UPSTREAM",
    )
    # Empty-list case still emits one row so the ECLI is represented in
    # fulltexts.parquet (otherwise we'd lose the missing_reasons trail).
    assert len(records) == 1
    assert records[0]["text"] == ""
    assert records[0]["missing_reasons"] == "FULLTEXT_UNAVAILABLE_UPSTREAM"
