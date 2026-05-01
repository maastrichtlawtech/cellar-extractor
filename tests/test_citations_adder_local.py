from io import StringIO

import pandas as pd
import pytest

from cellar_extractor import citations_adder


def test_allowed_id_accepts_celex_prefix_6_or_8():
    assert citations_adder.allowed_id("62023CJ0800")
    assert citations_adder.allowed_id("82025CZ0825(51)")
    assert not citations_adder.allowed_id("32013R0575")


def test_add_citations_separate_maps_citing_and_cited(monkeypatch):
    data = pd.DataFrame({"celex": ["A", "B"]})

    def _fake_execute(relations_list, citations):
        relations_list.append(
            StringIO(
                "celex,citedD,direction\n"
                "A,CITED_A,inbound\n"
                "B,CITED_B,inbound\n"
                "A,CITING_A,outbound\n"
                "B,CITING_B,outbound\n"
            )
        )

    monkeypatch.setattr(citations_adder, "execute_citations_separate", _fake_execute)

    citations_adder.add_citations_separate(data, threads=2)

    assert data.loc[0, "cited_by"] == "CITED_A"
    assert data.loc[1, "cited_by"] == "CITED_B"
    assert data.loc[0, "citing"] == "CITING_A"
    assert data.loc[1, "citing"] == "CITING_B"


def test_add_citations_separate_keeps_rows_with_one_sided_relations(monkeypatch):
    data = pd.DataFrame({"celex": ["A", "B", "C"]})

    def _fake_execute(relations_list, citations):
        relations_list.append(
            StringIO(
                "celex,citedD,direction\n"
                "A,INBOUND_A,inbound\n"
                "B,OUTBOUND_B,outbound\n"
            )
        )

    monkeypatch.setattr(citations_adder, "execute_citations_separate", _fake_execute)

    citations_adder.add_citations_separate(data, threads=2)

    assert data.loc[0, "cited_by"] == "INBOUND_A"
    assert data.loc[0, "citing"] == ""
    assert data.loc[1, "cited_by"] == ""
    assert data.loc[1, "citing"] == "OUTBOUND_B"
    assert data.loc[2, "cited_by"] == ""
    assert data.loc[2, "citing"] == ""


def test_add_citations_separate_deduplicates_relations(monkeypatch):
    data = pd.DataFrame({"celex": ["A"]})

    def _fake_execute(relations_list, citations):
        relations_list.append(
            StringIO(
                "celex,citedD,direction\n"
                "A,X,inbound\n"
                "A,X,inbound\n"
                "A,Y,inbound\n"
                "A,Z,outbound\n"
                "A,Z,outbound\n"
            )
        )

    monkeypatch.setattr(citations_adder, "execute_citations_separate", _fake_execute)

    citations_adder.add_citations_separate(data, threads=1)

    assert data.loc[0, "cited_by"] == "X;Y"
    assert data.loc[0, "citing"] == "Z"


def test_add_citations_separate_deduplicates_duplicate_input_celexes(monkeypatch):
    data = pd.DataFrame({"celex": ["A", "A", "B"]})
    seen = []

    def _fake_execute(relations_list, citations):
        seen.append(list(citations))
        relations_list.append(
            StringIO(
                "celex,citedD,direction\n"
                "A,X,outbound\n"
                "B,Y,inbound\n"
            )
        )

    monkeypatch.setattr(citations_adder, "execute_citations_separate", _fake_execute)

    citations_adder.add_citations_separate(data, threads=3)

    assert sorted(tuple(batch) for batch in seen) in ([("A", "B")], [("A",), ("B",)])
    assert data.loc[0, "citing"] == "X"
    assert data.loc[1, "citing"] == "X"
    assert data.loc[2, "cited_by"] == "Y"


def test_add_citations_separate_webservice_warns_on_use(monkeypatch):
    data = pd.DataFrame({"celex": ["62019CJ0668"]})

    class _Response:
        status_code = 200
        text = "<searchResults/>"

    monkeypatch.setattr(citations_adder, "run_eurlex_webservice_query", lambda *_args: _Response())
    monkeypatch.setattr(citations_adder, "execute_citations_webservice", lambda *args: None)

    with pytest.warns(DeprecationWarning, match="deprecated"):
        citations_adder.add_citations_separate_webservice(data, "user", "pass")
