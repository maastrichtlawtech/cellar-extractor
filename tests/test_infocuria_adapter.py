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


def test_choose_best_document_requires_requested_celex_before_type_priority():
    docs = [
        {
            "content": {
                "docLang": "EN",
                "docFormats": ["HTML"],
                "logicDocId": "id_judgment",
                "idProcedure": "C/0444/11/00000000RP/01/P/01",
                "docTypeCode": "ARRET",
                "celex": "62011CJ0444",
            }
        },
        {
            "content": {
                "docLang": "EN",
                "docFormats": ["HTML"],
                "logicDocId": "id_order",
                "idProcedure": "C/0444/11/00000000RP/01/P/01",
                "docTypeCode": "ORDONNANCE",
                "celex": "62011CO0444",
            }
        },
    ]

    selected = eurlex_scraping._choose_best_document(
        docs,
        language="EN",
        celex="62011CO0444",
    )

    assert selected["logicDocId"] == "id_order"
    assert (
        eurlex_scraping._choose_best_document(
            docs,
            language="EN",
            celex="62011CC0444",
        )
        is None
    )


def test_normalize_celex_converts_infocuria_dot_variant():
    assert eurlex_scraping.normalize_celex("62011FO0005.01") == "62011FO0005(01)"


def test_extract_summary_from_documents_prefers_summary_marker():
    docs = [
        {
            "content": {
                "docTypeCode": "ARRET",
                "contentML": [{"en": "Judgment content without marker"}],
            }
        },
        {
            "content": {
                "docTypeCode": "DDP",
                "contentML": [{"en": "Header\nSummary of the request\nBody"}],
            }
        },
    ]

    summary = eurlex_scraping._extract_summary_from_documents(docs, language="en")

    assert summary.startswith("Summary")


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
            "affecting_string": "joined: C-1/20",
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
                            "advocateML": [
                                {"code": "KOK", "label": [{"en": "Kokott"}]}
                            ],
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
                                            "logicDocId": "id_316845",
                                            "idProcedure": "C/0131/24/00000000RP/01/P/01",
                                            "docTypeCode": "ARRET",
                                            "contentML": [
                                                {
                                                    "en": "Preface\nSummary of the case\nAdditional lines"
                                                }
                                            ],
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

    class _FakeSession:
        def get(self, url, timeout=60):
            return _fake_get(url, timeout=timeout)

    monkeypatch.setattr(eurlex_scraping, "_post_json", _fake_post)
    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _FakeSession())
    # Sector 6 now also supplements with CELLAR's multi-language manifestation
    # graph. For this InfoCuria-focused test, stub the CELLAR side so it
    # noops — supplementation behaviour itself is covered in
    # test_sector6_cellar_supplement.py.
    monkeypatch.setattr(
        eurlex_scraping,
        "_fetch_sector8_work_uri",
        lambda celex, sector="8": "",
    )

    data = eurlex_scraping.get_case_data_by_celex_id("62024CJ0131", language="EN")

    assert data["html"] != ""
    assert data["summary"].startswith("Summary")
    assert data["keywords"] == "Environment"
    assert data["directory_codes"] == "ENVI"
    assert data["advocate"] == "Kokott"
    assert data["judge"] == "Spielmann"
    assert data["affecting_ids"] == "C-2/20"
    assert data["sector"] == "6"
    assert data["text_source"] == "INFOCURIA_BLOB_HTML"
    assert data["summary_source"] == "INFOCURIA_DOCUMENT_CONTENT"
    assert data["missing_reasons"] == ""
    assert "316845-EN-1.html" in requested_urls[0]
    eurlex_scraping._get_case_data_cached.cache_clear()



def test_choose_best_document_selects_catalogued_document_id():
    docs = [
        {"content": {"logicDocId": "id_60942", "idProcedure": "C/0193/07/R", "docFormats": ["HTML"],
                     "celex": "62007CO0193", "docTypeCode": "ORD_NP", "docLang": "EN"}},
        {"content": {"logicDocId": "id_60821", "idProcedure": "C/0193/07/P", "docFormats": ["HTML"],
                     "celex": "62007CO0193", "docTypeCode": "ORD_NP", "docLang": "EN"}},
    ]

    selected = eurlex_scraping._choose_best_document(docs, language="EN", document_id="id_60821")
    missing = eurlex_scraping._choose_best_document(docs, language="EN", document_id="60000")

    assert selected["logicDocId"] == "id_60821"
    assert missing is None


def test_sector6_without_confirmed_celex_never_queries_cellar(monkeypatch):
    def _no_cellar(*args, **kwargs):
        raise AssertionError("CELLAR must not be queried")

    monkeypatch.setattr(eurlex_scraping, "_post_json", lambda url, payload, retries=3: [])
    monkeypatch.setattr(eurlex_scraping, "_get_case_data_sector6_cellar_fallback", _no_cellar)
    monkeypatch.setattr(eurlex_scraping, "_fetch_sector8_items_for_celex", _no_cellar)

    assert eurlex_scraping._get_case_data_sector6(
        "62007CO0193", language="EN", document_id="id_60821", use_cellar=False
    ) is None


def test_sector6_finds_document_in_any_procedure_root(monkeypatch):
    roots = {
        "searchHits": [
            {"content": {}, "innerHits": {"document": {"searchHits": [
                {"content": {"logicDocId": "id_70803", "idProcedure": "C/0193/07/00000000RD/01/P/01",
                             "docFormats": ["HTML"], "docLang": "FR", "docTypeCode": "ORD_NP"}}]}}},
            {"content": {}, "innerHits": {"document": {"searchHits": [
                {"content": {"logicDocId": "id_60942", "idProcedure": "C/0193/07/00000000RD/01/R/01",
                             "docFormats": ["HTML"], "docLang": "FR", "docTypeCode": "ORD_NP"}}]}}},
        ]
    }

    def _post(url, payload, retries=3):
        if url == eurlex_scraping.INFOCURIA_SUGGEST:
            return [{"procedureDocInfo": {"idPublished": "C-193/07", "id": "C/0193/07/00000000RD/01/P/01-1"}}]
        return roots

    requested = []

    class _Session:
        def get(self, url, timeout):
            requested.append(url)
            return type("R", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(eurlex_scraping, "_post_json", _post)
    monkeypatch.setattr(eurlex_scraping, "_get_http_session", lambda: _Session())
    monkeypatch.setattr(eurlex_scraping, "_pace_requests", lambda *a, **k: None)

    eurlex_scraping._get_case_data_sector6(
        "62007CO0193", language="EN", document_id="id_60942", use_cellar=False
    )

    assert requested and "60942-FR" in requested[0]
