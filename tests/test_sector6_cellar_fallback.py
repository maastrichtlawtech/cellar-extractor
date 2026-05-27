"""Tests for the sector-6 CELLAR fallback (pre-2001 fulltext fix).

Older CJEU judgments (typically pre-2001) are not indexed by InfoCuria's
REST API, but CELLAR carries body text for nearly all of them — sector 8's
existing manifestation-fetching machinery just needs to be invoked.

These tests cover:
  * The fallback triggers when InfoCuria's /suggest returns an empty list.
  * The fallback triggers when /procedures returns no searchHits.
  * The fallback skips when InfoCuria succeeds (existing path unchanged).
  * The fallback dict carries text_source=CELLAR_ITEM, sector="6", and
    the keywords / subject labels CELLAR provides.
  * When BOTH InfoCuria and CELLAR are empty the row reports
    FULLTEXT_UNAVAILABLE_UPSTREAM.
"""
from __future__ import annotations

import pytest

from cellar_extractor import eurlex_scraping


# ---------------------------------------------------------------------------
# Helpers — small patching utilities to keep each test focused.
# ---------------------------------------------------------------------------


def _stub_infocuria_empty(monkeypatch, *, suggest_empty=True, procedures_empty=False):
    """Patch InfoCuria to return either nothing on /suggest, or nothing on
    /procedures (the two cases that today produce a None fulltext row)."""
    def _post(url, payload, retries=3):
        if url.endswith("/suggest"):
            return [] if suggest_empty else [
                {"procedureDocInfo": {
                    "id": "C/0001/64/00000000RP/01/P/01-999",
                    "idPublished": "C-6/64",
                }}
            ]
        if url.endswith("/affairId/procedures"):
            return {"searchHits": []} if procedures_empty else {"searchHits": []}
        return None
    monkeypatch.setattr(eurlex_scraping, "_post_json", _post)


def _stub_cellar_with_payload(
    monkeypatch,
    *,
    work_uri="http://publications.europa.eu/resource/cellar/test-uuid",
    items=None,
    subject_labels=("Free movement of goods", "Customs Union"),
    item_payload=("Body text of Costa v ENEL", "<html>body</html>", "html"),
):
    """Patch the CELLAR SPARQL + item-fetch helpers to return a working
    sector-6 case with EN fulltext + a couple of subject labels."""
    if items is None:
        items = [{
            "item_url": work_uri + "/DOC_1",
            "format": "xhtml",
            "language": "EN",
        }]

    monkeypatch.setattr(
        eurlex_scraping, "_fetch_sector8_work_uri",
        lambda celex, sector="8": work_uri,
    )
    monkeypatch.setattr(
        eurlex_scraping, "_fetch_sector8_items_for_work",
        lambda uri: items,
    )
    monkeypatch.setattr(
        eurlex_scraping, "_fetch_sector8_subject_labels",
        lambda uri, language="en": list(subject_labels),
    )
    monkeypatch.setattr(
        eurlex_scraping, "_extract_item_payload",
        lambda url, fmt: item_payload,
    )


def _stub_cellar_empty(monkeypatch):
    monkeypatch.setattr(
        eurlex_scraping, "_fetch_sector8_work_uri",
        lambda celex, sector="8": "",
    )


# ---------------------------------------------------------------------------
# Behaviour tests
# ---------------------------------------------------------------------------


def test_fallback_triggers_when_infocuria_suggest_empty(monkeypatch):
    """The pre-2001 case where InfoCuria has nothing for the CELEX."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _stub_infocuria_empty(monkeypatch, suggest_empty=True)
    _stub_cellar_with_payload(monkeypatch)

    data = eurlex_scraping._get_case_data_sector6("61964CJ0006", language="EN")

    assert data is not None, "fallback should produce a row when CELLAR has the case"
    assert data["text"] == "Body text of Costa v ENEL"
    assert data["text_source"] == "CELLAR_ITEM"
    assert data["text_language"] == "EN"
    assert data["sector"] == "6"


def test_fallback_keywords_come_from_cellar_subject_labels(monkeypatch):
    """When falling back to CELLAR the keywords + eurovoc columns are
    populated from CDM subject-matter labels — otherwise the row would
    be metadata-empty."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _stub_infocuria_empty(monkeypatch, suggest_empty=True)
    _stub_cellar_with_payload(
        monkeypatch,
        subject_labels=("Free movement of goods", "Customs Union"),
    )

    data = eurlex_scraping._get_case_data_sector6("61964CJ0006", language="EN")

    assert "Free movement of goods" in data["keywords"]
    assert "Customs Union" in data["keywords"]
    assert data["eurovoc"] == data["keywords"]  # mirror, as elsewhere


def test_fallback_returns_none_when_cellar_also_empty(monkeypatch):
    """Belt-and-braces: if neither InfoCuria nor CELLAR has the case,
    surface that as None (so missing_reasons gets set upstream)."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _stub_infocuria_empty(monkeypatch, suggest_empty=True)
    _stub_cellar_empty(monkeypatch)

    data = eurlex_scraping._get_case_data_sector6("61964CJ9999", language="EN")
    assert data is None


def test_fallback_handles_pdf_format(monkeypatch):
    """Some old judgments only have PDF manifestations — they should still
    yield body text via _extract_item_payload's PDF branch."""
    eurlex_scraping._get_case_data_cached.cache_clear()
    _stub_infocuria_empty(monkeypatch, suggest_empty=True)
    _stub_cellar_with_payload(
        monkeypatch,
        items=[{
            "item_url": "http://publications.europa.eu/resource/cellar/uuid/DOC_1",
            "format": "pdf",
            "language": "EN",
        }],
        item_payload=("Body text extracted from PDF", "", "pdf"),
    )

    data = eurlex_scraping._get_case_data_sector6("61964CJ0006", language="EN")

    assert data["text"].startswith("Body text extracted from PDF")
    assert data["text_format"] == "pdf"


def test_fallback_does_not_run_when_infocuria_succeeds(monkeypatch):
    """The legacy InfoCuria path must keep working unchanged for modern
    (post-2001) cases — the fallback is only a safety net."""
    eurlex_scraping._get_case_data_cached.cache_clear()

    sparql_called = []

    def _fake_post(url, payload, retries=3):
        if url.endswith("/suggest"):
            return [{"procedureDocInfo": {
                "id": "C/0131/24/00000000RP/01/P/01-999",
                "idPublished": "C-131/24",
            }}]
        if url.endswith("/affairId/procedures"):
            return {
                "searchHits": [{
                    "content": {
                        "matCodeML": [{"label": [{"en": "Environment"}]}],
                        "matCode": ["ENVI"],
                        "advocateML": [], "avg": "",
                        "reportingJudgeML": [], "reportingJudge": "",
                        "joinAffairs": [], "procedureResultTypeML": [],
                        "parties": "",
                    },
                    "innerHits": {"document": {"searchHits": [{
                        "content": {
                            "docLang": "EN", "docFormats": ["HTML"],
                            "logicDocId": "id_1",
                            "idProcedure": "C/0131/24/00000000RP/01/P/01",
                            "docTypeCode": "ARRET",
                        }
                    }]}},
                }]
            }
        return None

    monkeypatch.setattr(eurlex_scraping, "_post_json", _fake_post)

    # InfoCuria blob fetch
    class _Resp:
        status_code = 200
        text = "<html>modern judgment body</html>"

    class _Session:
        def get(self, url, timeout=60):
            return _Resp()

    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _Session())

    # The CELLAR helper must NOT be invoked.
    def _no_call_work_uri(*args, **kwargs):
        sparql_called.append(args)
        raise AssertionError("CELLAR fallback should not run when InfoCuria succeeds")

    monkeypatch.setattr(eurlex_scraping, "_fetch_sector8_work_uri", _no_call_work_uri)

    data = eurlex_scraping._get_case_data_sector6("62024CJ0131", language="EN")

    assert data is not None
    assert data["text_source"] == "INFOCURIA_BLOB_HTML"
    assert sparql_called == []  # double-check


def test_fetch_work_uri_accepts_sector_parameter(monkeypatch):
    """The work-URI lookup must be sector-aware so the same function serves
    both sector 6 (CJEU) and sector 8 (national courts)."""
    queries = []

    def _fake_query(query):
        queries.append(query)
        return {"results": {"bindings": [
            {"doc": {"value": "http://publications.europa.eu/resource/cellar/abc"}}
        ]}}

    monkeypatch.setattr(eurlex_scraping, "_query_cellar_sparql", _fake_query)

    uri6 = eurlex_scraping._fetch_sector8_work_uri("61964CJ0006", sector="6")
    uri8 = eurlex_scraping._fetch_sector8_work_uri("82023DE0001", sector="8")

    assert uri6 == "http://publications.europa.eu/resource/cellar/abc"
    assert uri8 == "http://publications.europa.eu/resource/cellar/abc"
    assert 'FILTER(STR(?sector) = "6")' in queries[0]
    assert 'FILTER(STR(?sector) = "8")' in queries[1]
