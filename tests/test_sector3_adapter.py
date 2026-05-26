from cellar_extractor import eurlex_scraping


def test_dispatch_routes_sector3_celex_to_sector3_handler(monkeypatch):
    eurlex_scraping._get_case_data_cached.cache_clear()

    monkeypatch.setattr(
        eurlex_scraping,
        "_get_case_data_sector3",
        lambda celex, language="EN": {"sector": "3", "celex": celex},
    )

    data = eurlex_scraping.get_case_data_by_celex_id("32016R0679", language="EN")

    assert data["sector"] == "3"
    assert data["celex"] == "32016R0679"
    eurlex_scraping._get_case_data_cached.cache_clear()


def test_dispatch_routes_consolidated_celex_to_sector3_handler(monkeypatch):
    eurlex_scraping._get_case_data_cached.cache_clear()

    monkeypatch.setattr(
        eurlex_scraping,
        "_get_case_data_sector3",
        lambda celex, language="EN": {"sector": "3", "celex": celex},
    )

    data = eurlex_scraping.get_case_data_by_celex_id(
        "02002L0058-20091219", language="EN"
    )

    assert data["sector"] == "3"
    assert data["celex"] == "02002L0058-20091219"
    eurlex_scraping._get_case_data_cached.cache_clear()


def test_get_legislation_by_celex_id_uses_dispatch(monkeypatch):
    eurlex_scraping._get_case_data_cached.cache_clear()

    monkeypatch.setattr(
        eurlex_scraping,
        "_get_case_data_sector3",
        lambda celex, language="EN": {"sector": "3", "celex": celex, "language": language},
    )

    data = eurlex_scraping.get_legislation_by_celex_id("32024R1689", language="en")

    assert data["sector"] == "3"
    assert data["celex"] == "32024R1689"
    assert data["language"] == "EN"
    eurlex_scraping._get_case_data_cached.cache_clear()


def test_fetch_sector3_xhtml_sends_xhtml_accept_header(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = "<html><body>Article 1</body></html>"
        headers = {"Content-Language": "eng"}

    class _FakeSession:
        def get(self, url, headers=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _FakeSession())

    body, lang = eurlex_scraping._fetch_sector3_xhtml("32016R0679", language="EN")

    assert body == "<html><body>Article 1</body></html>"
    assert lang == "eng"
    assert captured["url"].endswith("/celex/32016R0679")
    assert captured["headers"]["Accept"] == "application/xhtml+xml"
    assert captured["headers"]["Accept-Language"] == "eng"


def test_fetch_sector3_xhtml_returns_empty_on_404(monkeypatch):
    class _Resp:
        status_code = 404
        text = ""
        headers = {}

    class _FakeSession:
        def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _FakeSession())

    body, lang = eurlex_scraping._fetch_sector3_xhtml("39999R9999", language="EN")

    assert body == ""
    assert lang == ""


def test_get_case_data_sector3_builds_payload_from_xhtml(monkeypatch):
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector3_xhtml",
        lambda celex, language="EN": (
            "<html><body><p>This Regulation lays down rules.</p></body></html>",
            "eng",
        ),
    )

    data = eurlex_scraping._get_case_data_sector3("32016R0679", language="EN")

    assert data["sector"] == "3"
    assert data["text_source"] == "CELLAR_REST_XHTML"
    assert data["text_format"] == "xhtml"
    assert data["text_language"] == "EN"
    assert "lays down rules" in data["text"]
    assert "<html>" in data["html"]
    assert data["summary"] == ""
    assert "FULLTEXT_UNAVAILABLE_UPSTREAM" not in data["missing_reasons"]
    assert "SUMMARY_UNAVAILABLE_UPSTREAM" in data["missing_reasons"]


def test_get_case_data_sector3_tags_consolidated_celex_with_sector_zero(monkeypatch):
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector3_xhtml",
        lambda celex, language="EN": (
            "<html><body><p>Consolidated text.</p></body></html>",
            "eng",
        ),
    )

    data = eurlex_scraping._get_case_data_sector3("02002L0058-20091219", language="EN")

    assert data["sector"] == "0"
    assert "Consolidated" in data["text"]


def test_get_case_data_sector3_unavailable_sets_missing_reasons(monkeypatch):
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector3_xhtml",
        lambda celex, language="EN": ("", ""),
    )

    data = eurlex_scraping._get_case_data_sector3("39999R9999", language="EN")

    assert data["text"] == ""
    assert data["html"] == ""
    assert data["text_source"] == ""
    assert "FULLTEXT_UNAVAILABLE_UPSTREAM" in data["missing_reasons"]
    assert "SUMMARY_UNAVAILABLE_UPSTREAM" in data["missing_reasons"]
    assert "UNAVAILABLE_UPSTREAM" in data["missing_reasons"]
