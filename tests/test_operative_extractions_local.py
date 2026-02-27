from cellar_extractor.operative_extractions import FetchOperativePart


class _FakeSparql:
    def __init__(self, payload):
        self.payload = payload
        self.query = ""

    def setReturnFormat(self, _fmt):
        return None

    def setQuery(self, query):
        self.query = query

    def queryAndConvert(self):
        return self.payload


def test_get_operative_sparql_query_includes_owl_prefix():
    payload = {"results": {"bindings": []}}
    fetcher = FetchOperativePart("61986CJ0062")
    fake = _FakeSparql(payload)
    fetcher.sparql = fake

    fetcher.get_operative_sparql()

    assert "PREFIX owl:" in fake.query


def test_get_operative_sparql_parses_html():
    payload = {
        "results": {
            "bindings": [{"operative": {"value": "<p>Operative text</p>"}}],
        }
    }
    fetcher = FetchOperativePart("61986CJ0062")
    fetcher.sparql = _FakeSparql(payload)

    result = fetcher.get_operative_sparql()

    assert result == "Operative text"
