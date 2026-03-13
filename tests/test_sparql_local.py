import pytest

from cellar_extractor import sparql


class _FakeSparql:
    def __init__(self, payload):
        self.payload = payload
        self.query = ""

    def setReturnFormat(self, *_args, **_kwargs):
        return None

    def setQuery(self, query):
        self.query = query

    def queryAndConvert(self):
        return self.payload


def test_get_citations_omits_reverse_branch_when_cited_depth_zero(monkeypatch):
    payload = {
        "results": {
            "bindings": [
                {"name2": {"value": "62000CJ0001"}},
                {"name2": {"value": "62000CJ0001"}},
                {"name2": {"value": "62000CJ0002"}},
            ]
        }
    }
    fake = _FakeSparql(payload)
    monkeypatch.setattr(sparql, "SPARQLWrapper", lambda *_args, **_kwargs: fake)

    result = sparql.get_citations("62000CJ0003", cites_depth=1, cited_depth=0)

    assert result == {"62000CJ0001", "62000CJ0002"}
    assert "?doc cdm:work_cites_work{1,1} ?cited" in fake.query
    assert "?cited cdm:work_cites_work" not in fake.query
    assert "UNION" not in fake.query


def test_get_citations_requires_positive_depth():
    with pytest.raises(ValueError, match="greater than zero"):
        sparql.get_citations("62000CJ0003", cites_depth=0, cited_depth=0)
