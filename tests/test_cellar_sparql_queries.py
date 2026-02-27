from cellar_extractor.cellar_sparql_queries import CellarSparqlQuery


class _FakeSparql:
    def __init__(self, payload):
        self.payload = payload
        self.query = ""

    def setQuery(self, query):
        self.query = query

    def queryAndConvert(self):
        return self.payload


def test_get_grounds_strips_html_tags():
    payload = {
        "results": {
            "bindings": [
                {"value": {"value": "<p>Alpha</p><p>Beta</p>"}},
            ]
        }
    }
    query = CellarSparqlQuery()
    query.sparql = _FakeSparql(payload)

    result = query.get_grounds("61986CJ0062")

    assert result == "AlphaBeta"


def test_get_endorsements_empty_result_is_empty_string():
    payload = {"results": {"bindings": []}}
    query = CellarSparqlQuery()
    query.sparql = _FakeSparql(payload)

    result = query.get_endorsements("61963CO0111")

    assert result == ""


def test_get_citations_deduplicates_targets():
    payload = {
        "results": {
            "bindings": [
                {"name2": {"value": "62000CJ0001"}},
                {"name2": {"value": "62000CJ0001"}},
                {"name2": {"value": "62000CJ0002"}},
            ]
        }
    }
    query = CellarSparqlQuery()
    query.sparql = _FakeSparql(payload)

    result = query.get_citations("62000CJ0003")

    assert set(result) == {"62000CJ0001", "62000CJ0002"}


def test_get_grounds_query_no_longer_relies_on_eng_manifestation_uri():
    payload = {"results": {"bindings": []}}
    query = CellarSparqlQuery()
    fake = _FakeSparql(payload)
    query.sparql = fake

    query.get_grounds("82010AT0127(51)")

    assert "resource/celex/82010AT0127(51).ENG.txt" not in fake.query
    assert 'cdm:resource_legal_id_celex "82010AT0127(51)"' in fake.query
