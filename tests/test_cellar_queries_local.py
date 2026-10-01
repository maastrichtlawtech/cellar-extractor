import re

import pytest

from cellar_extractor import cellar_queries


class _FakeSparql:
    def __init__(self, payload):
        self.payload = payload
        self.query = ""
        self.method = None
        self.timeout = None

    def setReturnFormat(self, *_args, **_kwargs):
        return None

    def setMethod(self, method):
        self.method = method

    def setQuery(self, query):
        self.query = query

    def setTimeout(self, seconds):
        self.timeout = seconds

    def queryAndConvert(self):
        return self.payload


def test_get_all_eclis_includes_limit_when_requested(monkeypatch):
    payload = {"results": {"bindings": [{"ecli": {"value": "ECLI:EU:C:2025:1"}}]}}
    fake = _FakeSparql(payload)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)

    result = cellar_queries.get_all_eclis(
        starting_date="2025-01-01",
        ending_date="2025-01-31",
        limit=1,
    )

    assert result == ["ECLI:EU:C:2025:1"]
    assert "LIMIT 1" in fake.query
    assert 'FILTER(STR(?date) >= "2025-01-01")' in fake.query
    assert 'FILTER(STR(?date) <= "2025-01-31")' in fake.query


def test_get_all_eclis_supports_single_day_window(monkeypatch):
    """sd == ed is a valid one-day window. Filter uses >=/<= so both endpoints
    are inclusive — a doc with date_document == sd == ed should match."""
    payload = {"results": {"bindings": [{"ecli": {"value": "ECLI:EU:C:2025:1"}}]}}
    fake = _FakeSparql(payload)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)

    result = cellar_queries.get_all_eclis(
        starting_date="2025-06-15",
        ending_date="2025-06-15",
        limit=10,
    )

    assert result == ["ECLI:EU:C:2025:1"]
    assert 'FILTER(STR(?date) >= "2025-06-15")' in fake.query
    assert 'FILTER(STR(?date) <= "2025-06-15")' in fake.query


def test_get_all_eclis_handles_timestamped_end_date(monkeypatch):
    """``ed`` may carry a time suffix (e.g. '2025-12-31T23:59:59'). The filter
    is lexicographic on the date string and YYYY-MM-DD < YYYY-MM-DDT...,
    so a doc dated YYYY-MM-DD passes ``<= YYYY-MM-DDT23:59:59``."""
    payload = {"results": {"bindings": []}}
    fake = _FakeSparql(payload)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)

    cellar_queries.get_all_eclis(
        starting_date="2020-01-01",
        ending_date="2020-12-31T23:59:59",
        limit=5,
    )

    assert 'FILTER(STR(?date) >= "2020-01-01")' in fake.query
    assert 'FILTER(STR(?date) <= "2020-12-31T23:59:59")' in fake.query


def test_get_all_eclis_returns_empty_for_empty_window(monkeypatch):
    """A date range with no matching documents returns an empty list,
    not an error."""
    payload = {"results": {"bindings": []}}
    fake = _FakeSparql(payload)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)

    result = cellar_queries.get_all_eclis(
        starting_date="1900-01-01",
        ending_date="1900-12-31",
        limit=100,
    )

    assert result == []


def test_get_raw_cellar_metadata_filters_requested_eclis(monkeypatch):
    payload = {
        "results": {
            "bindings": [
                {
                    "ecli": {"value": "ECLI:EU:C:2025:1"},
                    "p": {
                        "value": "http://publications.europa.eu/ontology/cdm#case-law_ecli"
                    },
                    "o": {"value": "ECLI:EU:C:2025:1"},
                }
            ]
        }
    }
    fake = _FakeSparql(payload)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)

    result = cellar_queries.get_raw_cellar_metadata(["ECLI:EU:C:2025:1"])

    # Property keys are now CDM predicate URI local parts, not rdfs:label.
    assert result["ECLI:EU:C:2025:1"]["case-law_ecli"] == ["ECLI:EU:C:2025:1"]
    assert 'FILTER(STR(?ecli) in ("ECLI:EU:C:2025:1"))' in fake.query
    assert fake.method == cellar_queries.POST


class _WindowedFakeSparql:
    def __init__(self, responses):
        self.responses = responses
        self.query = ""
        self.queries = []

    def setReturnFormat(self, *_args, **_kwargs):
        return None

    def setMethod(self, *_args, **_kwargs):
        return None

    def setQuery(self, query):
        self.query = query
        self.queries.append(query)

    def setTimeout(self, *_args, **_kwargs):
        return None

    def queryAndConvert(self):
        start = re.search(r'FILTER\(STR\(\?date\) >= "([^"]+)"\)', self.query).group(1)
        end = re.search(r'FILTER\(STR\(\?date\) <= "([^"]+)"\)', self.query).group(1)
        return self.responses[(start, end)]


def test_get_all_eclis_chunks_large_sorted_requests(monkeypatch):
    responses = {
        ("2025-01-01", "2025-01-02"): {
            "results": {
                "bindings": [
                    {"ecli": {"value": "ECLI:EU:C:2025:2"}},
                    {"ecli": {"value": "ECLI:EU:C:2025:1"}},
                ]
            }
        },
        ("2025-01-03", "2025-01-04"): {
            "results": {
                "bindings": [
                    {"ecli": {"value": "ECLI:EU:C:2025:2"}},
                    {"ecli": {"value": "ECLI:EU:C:2025:3"}},
                ]
            }
        },
        ("2025-01-05", "2025-01-05"): {
            "results": {"bindings": [{"ecli": {"value": "ECLI:EU:C:2025:4"}}]}
        },
    }
    fake = _WindowedFakeSparql(responses)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr(cellar_queries, "MAX_SORTED_TOP_LIMIT", 3)
    monkeypatch.setattr(cellar_queries, "ECLI_WINDOW_DAYS", 2)

    result = cellar_queries.get_all_eclis(
        starting_date="2025-01-01",
        ending_date="2025-01-05",
        limit=50,
    )

    assert result == [
        "ECLI:EU:C:2025:1",
        "ECLI:EU:C:2025:2",
        "ECLI:EU:C:2025:3",
        "ECLI:EU:C:2025:4",
    ]
    assert len(fake.queries) == 3
    assert all("LIMIT 50" not in query for query in fake.queries)


def test_get_all_eclis_applies_large_limit_locally_after_chunking(monkeypatch):
    responses = {
        ("2025-01-01", "2025-01-02"): {
            "results": {
                "bindings": [
                    {"ecli": {"value": "ECLI:EU:C:2025:2"}},
                    {"ecli": {"value": "ECLI:EU:C:2025:1"}},
                ]
            }
        },
        ("2025-01-03", "2025-01-04"): {
            "results": {"bindings": [{"ecli": {"value": "ECLI:EU:C:2025:3"}}]}
        },
    }
    fake = _WindowedFakeSparql(responses)
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr(cellar_queries, "MAX_SORTED_TOP_LIMIT", 2)
    monkeypatch.setattr(cellar_queries, "ECLI_WINDOW_DAYS", 2)

    result = cellar_queries.get_all_eclis(
        starting_date="2025-01-01",
        ending_date="2025-01-04",
        limit=3,
    )

    assert result == ["ECLI:EU:C:2025:1", "ECLI:EU:C:2025:2", "ECLI:EU:C:2025:3"]
    assert len(fake.queries) == 2


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_infocuria_catalog_paginates_and_normalizes_document_variants(monkeypatch):
    calls = []
    pages = [
        {
            "totalHits": 3,
            "searchHits": [
                {
                    "content": {
                        "ecli": "ECLI:EU:F:2011:62",
                        "celex": "62011FO0005.01",
                        "docDate": "2011-05-12",
                        "docTypeCode": "ORDONNANCE",
                        "idPublished": "F-5/11",
                    }
                },
                {
                    "content": {
                        "ecli": "ECLI:EU:C:2011:1",
                        "celex": "62011CJ0001_SUM",
                        "docDate": "2011-05-13",
                    }
                },
            ],
        },
        {
            "totalHits": 3,
            "searchHits": [
                {
                    "content": {
                        "ecli": "ECLI:EU:C:2011:2",
                        "celex": "62011CO0002",
                        "docDate": "2011-05-14",
                        "idPublished": "C-2/11",
                    }
                }
            ],
        },
    ]

    def _post(url, json, timeout):
        calls.append((url, json, timeout))
        return _FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr(cellar_queries.requests, "post", _post)
    monkeypatch.setattr(cellar_queries, "INFOCURIA_PAGE_SIZE", 2)

    result = cellar_queries.get_infocuria_document_metadata(
        starting_date="2011-05-01",
        ending_date="2011-05-31",
    )

    assert set(result) == {"ECLI:EU:F:2011:62", "ECLI:EU:C:2011:2"}
    assert result["ECLI:EU:F:2011:62"]["resource_legal_id_celex"] == ["62011FO0005(01)"]
    assert result["ECLI:EU:F:2011:62"]["metadata_catalog_source"] == ["infocuria"]
    assert result["ECLI:EU:C:2011:2"]["resource_legal_type"] == ["CO"]
    assert calls[0][1]["pagination"]["from"] == 1
    assert calls[1][1]["pagination"]["from"] == 3
    assert calls[0][1]["filtersValue"] == [
        {"field": "docDate", "values": ["2011-05-01", "2011-05-31"]}
    ]


def test_reconcile_document_metadata_keeps_cellar_identity_and_adds_locator():
    cellar = {
        "ECLI:EU:T:2014:1": {
            "case-law_ecli": ["ECLI:EU:T:2014:1"],
            "resource_legal_id_celex": ["62013TO0505(01)"],
            "work_date_document": ["2014-01-08"],
            "subject_matter": ["Staff cases"],
        }
    }
    infocuria = {
        "ECLI:EU:T:2014:1": {
            "case-law_ecli": ["ECLI:EU:T:2014:1"],
            "resource_legal_id_celex": ["62013TO0505(02)"],
            "work_date_document": ["2014-01-08"],
            "metadata_catalog_source": ["infocuria"],
            "infocuria_celex": ["62013TO0505(02)"],
            "infocuria_document_id": ["id_146181"],
            "judge": ["Rapporteur"],
        },
        "ECLI:EU:T:2014:166": {
            "case-law_ecli": ["ECLI:EU:T:2014:166"],
            "resource_legal_id_celex": ["62013TO0505(03)"],
            "work_date_document": ["2014-03-19"],
            "infocuria_document_id": ["id_150082"],
        },
    }

    result = cellar_queries.reconcile_document_metadata(
        cellar, infocuria, celex_owners=lambda celex: set()
    )

    known = result["ECLI:EU:T:2014:1"]
    assert known["resource_legal_id_celex"] == ["62013TO0505(01)"]
    assert known["work_date_document"] == ["2014-01-08"]
    assert known["subject_matter"] == ["Staff cases"]
    assert known["judge"] == ["Rapporteur"]
    assert known["infocuria_document_id"] == ["id_146181"]
    assert known["metadata_catalog_source"] == ["infocuria"]
    assert known["identity_source"] == ["cellar"]
    only = result["ECLI:EU:T:2014:166"]
    assert only["resource_legal_id_celex"] == ["62013TO0505(03)"]
    assert only["identity_source"] == ["infocuria"]


def test_reconcile_document_metadata_drops_ambiguous_infocuria_celex():
    cellar = {
        "ECLI:EU:C:2014:10": {
            "case-law_ecli": ["ECLI:EU:C:2014:10"],
            "resource_legal_id_celex": ["62013CO0072"],
        }
    }

    def _only(ecli, celex, document_id):
        return {
            "case-law_ecli": [ecli],
            "resource_legal_id_celex": [celex],
            "resource_legal_type": ["CO"],
            "infocuria_celex": [celex],
            "infocuria_document_id": [document_id],
        }

    infocuria = {
        # Shares its procedure CELEX with a document CELLAR knows.
        "ECLI:EU:C:2015:1": _only("ECLI:EU:C:2015:1", "62013CO0072", "id_1"),
        # Two unpublished orders in one case, both labelled with the case CELEX.
        "ECLI:EU:C:2007:218": _only("ECLI:EU:C:2007:218", "62007CO0193", "id_2"),
        "ECLI:EU:C:2007:465": _only("ECLI:EU:C:2007:465", "62007CO0193", "id_3"),
        # Claimed by an ECLI CELLAR binds outside this window.
        "ECLI:EU:C:2016:1": _only("ECLI:EU:C:2016:1", "62016CO0001", "id_4"),
        # Unambiguous: kept.
        "ECLI:EU:C:2013:656": _only("ECLI:EU:C:2013:656", "62011CO0444", "id_5"),
    }
    owners = {"62016CO0001": {"ECLI:EU:C:2016:99"}}

    result = cellar_queries.reconcile_document_metadata(
        cellar, infocuria, celex_owners=lambda celex: owners.get(celex, set())
    )

    for ecli in (
        "ECLI:EU:C:2015:1",
        "ECLI:EU:C:2007:218",
        "ECLI:EU:C:2007:465",
        "ECLI:EU:C:2016:1",
    ):
        assert "resource_legal_id_celex" not in result[ecli]
        assert "resource_legal_type" not in result[ecli]
        assert result[ecli]["infocuria_document_id"]
    assert result["ECLI:EU:C:2014:10"]["resource_legal_id_celex"] == ["62013CO0072"]
    assert result["ECLI:EU:C:2013:656"]["resource_legal_id_celex"] == ["62011CO0444"]


def test_infocuria_celex_tokens_split_listed_values():
    assert cellar_queries._infocuria_celex_tokens(
        "62013CC0439 62013CC0439.01"
    ) == ["62013CC0439", "62013CC0439(01)"]
    assert cellar_queries._normalize_infocuria_celex("62013CC0439 62013CC0439.01") == ""
    assert cellar_queries._normalize_infocuria_celex("62011FO0005.01") == "62011FO0005(01)"
    assert cellar_queries._infocuria_celex_tokens("62011CJ0001_SUM") == []


def test_infocuria_catalog_prefers_decision_over_information_notice(monkeypatch):
    hit = {
        "ecli": "ECLI:EU:C:2015:632",
        "celex": "62015CO0001",
        "docDate": "2015-09-21",
        "idProcedure": "C/0001/15/00000000SA/01/P/01",
    }
    page = {
        "totalHits": 2,
        "searchHits": [
            {"content": {**hit, "docType": "Ordonnance (Information)", "logicDocId": "id_181188"}},
            {"content": {**hit, "docType": "Ordonnance", "logicDocId": "id_169861"}},
        ],
    }
    monkeypatch.setattr(
        cellar_queries.requests, "post", lambda url, json, timeout: _FakeResponse(page)
    )

    result = cellar_queries.get_infocuria_document_metadata(
        starting_date="2015-09-01", ending_date="2015-09-30"
    )

    record = result["ECLI:EU:C:2015:632"]
    assert record["infocuria_document_id"] == ["id_169861"]
    assert record["infocuria_procedure_id"] == ["C/0001/15/00000000SA/01/P/01"]
