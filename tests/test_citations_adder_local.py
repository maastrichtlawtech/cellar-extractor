from io import StringIO

import pandas as pd

from cellar_extractor import citations_adder


def test_allowed_id_accepts_celex_prefix_6_or_8():
    assert citations_adder.allowed_id("62023CJ0800")
    assert citations_adder.allowed_id("82025CZ0825(51)")
    assert not citations_adder.allowed_id("32013R0575")


def test_add_citations_separate_maps_citing_and_cited(monkeypatch):
    data = pd.DataFrame({"CELEX IDENTIFIER": ["A", "B"]})

    def _fake_execute(cited_list, citing_list, citations):
        cited_list.append(StringIO("celex,citedD\nA,CITED_A\nB,CITED_B\n"))
        citing_list.append(StringIO("celex,citedD\nA,CITING_A\nB,CITING_B\n"))

    monkeypatch.setattr(citations_adder, "execute_citations_separate", _fake_execute)

    citations_adder.add_citations_separate(data, threads=2)

    assert data.loc[0, "cited_by"] == "CITED_A"
    assert data.loc[1, "cited_by"] == "CITED_B"
    assert data.loc[0, "citing"] == "CITING_A"
    assert data.loc[1, "citing"] == "CITING_B"
