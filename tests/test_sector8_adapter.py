from cellar_extractor import eurlex_scraping


def test_case_data_dispatches_by_sector(monkeypatch):
    eurlex_scraping._get_case_data_cached.cache_clear()

    monkeypatch.setattr(
        eurlex_scraping,
        "_get_case_data_sector6",
        lambda celex, language="EN": {"sector": "6", "celex": celex},
    )
    monkeypatch.setattr(
        eurlex_scraping,
        "_get_case_data_sector8",
        lambda celex, language="EN": {"sector": "8", "celex": celex},
    )

    data6 = eurlex_scraping.get_case_data_by_celex_id("62024CJ0131", language="EN")
    data8 = eurlex_scraping.get_case_data_by_celex_id("82010AT0127(51)", language="EN")

    assert data6["sector"] == "6"
    assert data8["sector"] == "8"
    eurlex_scraping._get_case_data_cached.cache_clear()


def test_fetch_sector8_work_uri_uses_exact_celex_literal(monkeypatch):
    captured = {}

    def _fake_query(query, retries=3):
        captured["query"] = query
        return {
            "results": {
                "bindings": [
                    {"doc": {"value": "http://publications.europa.eu/resource/cellar/example"}}
                ]
            }
        }

    monkeypatch.setattr(eurlex_scraping, "_query_cellar_sparql", _fake_query)
    uri = eurlex_scraping._fetch_sector8_work_uri("82010AT0127(51)")

    assert uri.endswith("/example")
    assert 'FILTER(STR(?celex) = "82010AT0127(51)")' in captured["query"]


def test_choose_best_sector8_item_prefers_requested_language_then_format():
    candidates = [
        {"item_url": "a", "format": "pdf", "language": "FR"},
        {"item_url": "b", "format": "pdf", "language": "EN"},
        {"item_url": "c", "format": "xhtml", "language": "FR"},
    ]
    selected = eurlex_scraping._choose_best_sector8_item(candidates, language="EN", summary=False)
    assert selected["item_url"] == "b"

    selected_summary = eurlex_scraping._choose_best_sector8_item(
        candidates, language="FR", summary=True
    )
    assert selected_summary["item_url"] == "c"


def test_extract_item_payload_parses_html(monkeypatch):
    class _Resp:
        status_code = 200
        text = "<html><body>Hello <b>world</b>.</body></html>"
        content = text.encode("utf-8")
        headers = {"content-type": "text/html;charset=UTF-8"}

    monkeypatch.setattr(eurlex_scraping.requests, "get", lambda *args, **kwargs: _Resp())
    text, markup, fmt = eurlex_scraping._extract_item_payload("https://example.com/item", "xhtml")

    assert "Hello" in text
    assert "<html>" in markup
    assert fmt == "xhtml"


def test_extract_item_payload_parses_pdf(monkeypatch):
    class _Resp:
        status_code = 200
        text = ""
        content = b"%PDF-1.4 mock"
        headers = {"content-type": "application/pdf"}

    monkeypatch.setattr(eurlex_scraping.requests, "get", lambda *args, **kwargs: _Resp())
    monkeypatch.setattr(eurlex_scraping, "_parse_text_from_pdf", lambda content: "Extracted PDF text")

    text, markup, fmt = eurlex_scraping._extract_item_payload("https://example.com/item", "pdf")

    assert text == "Extracted PDF text"
    assert markup == ""
    assert fmt == "pdf"


def test_sector8_unavailable_sets_missing_reasons(monkeypatch):
    monkeypatch.setattr(eurlex_scraping, "_fetch_sector8_work_uri", lambda celex: "")
    data = eurlex_scraping._get_case_data_sector8("82000XX0001(01)", language="EN")

    assert data["text"] == ""
    assert data["summary"] == ""
    assert "FULLTEXT_UNAVAILABLE_UPSTREAM" in data["missing_reasons"]
    assert "SUMMARY_UNAVAILABLE_UPSTREAM" in data["missing_reasons"]
    assert "UNAVAILABLE_UPSTREAM" in data["missing_reasons"]
