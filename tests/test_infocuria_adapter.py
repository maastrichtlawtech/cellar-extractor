from cellar_extractor import eurlex_scraping


def test_published_id_from_celex():
    assert eurlex_scraping._published_id_from_celex("62024CJ0131") == "C-131/24"
    assert eurlex_scraping._published_id_from_celex("62024TJ0404") == "T-404/24"
    assert eurlex_scraping._published_id_from_celex("82025CZ0825") == ""


def test_extract_aff_id_from_suggest_identifier():
    aff_id, procedure = eurlex_scraping._extract_aff_id_from_suggest_identifier(
        "C/0131/24/00000000RP/01/P/01-3360046"
    )
    assert aff_id == "C/0131/24/00000000RP/01"
    assert procedure == "C/0131/24/00000000RP/01/P/01"


def test_choose_best_document_prefers_target_language():
    docs = [
        {
            "content": {
                "docLang": "FR",
                "docFormats": ["HTML"],
                "logicDocId": "id_1",
                "idProcedure": "C/0001/24/00000000RP/01/P/01",
                "docTypeCode": "ARRET",
            }
        },
        {
            "content": {
                "docLang": "EN",
                "docFormats": ["HTML"],
                "logicDocId": "id_2",
                "idProcedure": "C/0001/24/00000000RP/01/P/01",
                "docTypeCode": "ARRET",
            }
        },
    ]
    selected = eurlex_scraping._choose_best_document(docs, language="EN")
    assert selected["logicDocId"] == "id_2"


def test_get_entire_page_uses_infocuria_data(monkeypatch):
    monkeypatch.setattr(
        eurlex_scraping,
        "get_case_data_by_celex_id",
        lambda celex, language="EN": {
            "summary": "Summary text",
            "keywords": "kw1;kw2",
            "eurovoc": "Environment",
            "directory_codes": "15.20.10",
            "advocate": "Adv Name",
            "judge": "Judge Name",
            "affecting_strings": "C-1/20",
            "citations_extra": "Party A;Judgment",
        },
    )
    page = eurlex_scraping.get_entire_page("62024CJ0131")

    assert "Case law directory code:" in page
    assert "15.20.10" in page
    assert "Advocate General:Adv Name" in page


def test_get_case_data_by_celex_id_builds_blob_request(monkeypatch):
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
                            "advocateML": [{"code": "KOK", "label": [{"en": "Kokott"}]}],
                            "avg": "KOK",
                            "reportingJudgeML": [{"code": "SGE", "label": [{"en": "Spielmann"}]}],
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
                                            "logicDocId": "id_316845",
                                            "idProcedure": "C/0131/24/00000000RP/01/P/01",
                                            "docTypeCode": "ARRET",
                                        }
                                    }
                                ]
                            }
                        },
                    }
                ]
            }
        return None

    class _FakeResponse:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    requested_urls = []

    def _fake_get(url, timeout=60):
        requested_urls.append(url)
        return _FakeResponse(200, "<html><body>judgment text</body></html>")

    monkeypatch.setattr(eurlex_scraping, "_post_json", _fake_post)
    monkeypatch.setattr(eurlex_scraping.requests, "get", _fake_get)

    data = eurlex_scraping.get_case_data_by_celex_id("62024CJ0131", language="EN")

    assert data["html"] != ""
    assert data["keywords"] == "Environment"
    assert data["directory_codes"] == "ENVI"
    assert data["advocate"] == "Kokott"
    assert data["judge"] == "Spielmann"
    assert data["affecting_ids"] == "C-2/20"
    assert "316845-EN-1.html" in requested_urls[0]
    eurlex_scraping._get_case_data_cached.cache_clear()
