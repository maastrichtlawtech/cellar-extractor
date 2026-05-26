import pytest

from cellar_extractor import cellar_queries, sparql


class _AlwaysFailSparql:
    def __init__(self, *_args, **_kwargs):
        pass

    def setReturnFormat(self, *_args, **_kwargs):
        return None

    def setMethod(self, *_args, **_kwargs):
        return None

    def setQuery(self, *_args, **_kwargs):
        return None

    def setTimeout(self, *_args, **_kwargs):
        return None

    def queryAndConvert(self):
        raise RuntimeError("temporary failure")


def test_get_raw_cellar_metadata_stops_after_retries(monkeypatch):
    monkeypatch.setattr(cellar_queries, "SPARQLWrapper", _AlwaysFailSparql)

    with pytest.raises(RuntimeError, match="Failed to query CELLAR metadata after retries"):
        cellar_queries.get_raw_cellar_metadata(["ECLI:EU:C:2025:1"])


def test_get_citations_csv_stops_after_retries(monkeypatch):
    monkeypatch.setattr(sparql, "SPARQLWrapper", _AlwaysFailSparql)

    with pytest.raises(RuntimeError, match="Failed to fetch citations CSV after retries"):
        sparql.get_citations_csv(["62000CJ0001"])
