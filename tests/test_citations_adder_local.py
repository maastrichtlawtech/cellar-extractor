from io import StringIO

import pandas as pd
import pytest

from cellar_extractor import citations_adder


def test_allowed_id_accepts_celex_prefix_6_or_8():
    assert citations_adder.allowed_id("62023CJ0800")
    assert citations_adder.allowed_id("82025CZ0825(51)")
    assert not citations_adder.allowed_id("32013R0575")


def _patch_citation_sources(monkeypatch, uri_to_celex, get_cited_csv):
    """Monkeypatch the two upstream functions add_citations_separate now uses:
    `resolve_celexes_for_cellar_uris` for the outbound URI→CELEX mapping,
    and `get_cited` for the inbound SPARQL query."""
    monkeypatch.setattr(
        citations_adder,
        "resolve_celexes_for_cellar_uris",
        lambda uris, **_kw: {u: uri_to_celex[u] for u in uris if u in uri_to_celex},
    )
    monkeypatch.setattr(
        citations_adder,
        "get_cited",
        lambda celex, cited_depth, **_kw: get_cited_csv,
    )


def test_add_citations_separate_maps_citing_and_cited(monkeypatch):
    data = pd.DataFrame({
        "celex": ["A", "B"],
        "work_cites_work": ["http://uri/citing_a", "http://uri/citing_b"],
    })
    _patch_citation_sources(
        monkeypatch,
        uri_to_celex={
            "http://uri/citing_a": "CITING_A",
            "http://uri/citing_b": "CITING_B",
        },
        get_cited_csv="celex,citedD\nA,CITED_A\nB,CITED_B\n",
    )

    citations_adder.add_citations_separate(data, threads=2)

    assert data.loc[0, "cited_by"] == "CITED_A"
    assert data.loc[1, "cited_by"] == "CITED_B"
    assert data.loc[0, "citing"] == "CITING_A"
    assert data.loc[1, "citing"] == "CITING_B"


def test_add_citations_separate_keeps_rows_with_one_sided_relations(monkeypatch):
    data = pd.DataFrame({
        "celex": ["A", "B", "C"],
        "work_cites_work": ["", "http://uri/out_b", ""],
    })
    _patch_citation_sources(
        monkeypatch,
        uri_to_celex={"http://uri/out_b": "OUTBOUND_B"},
        get_cited_csv="celex,citedD\nA,INBOUND_A\n",
    )

    citations_adder.add_citations_separate(data, threads=2)

    assert data.loc[0, "cited_by"] == "INBOUND_A"
    assert data.loc[0, "citing"] == ""
    assert data.loc[1, "cited_by"] == ""
    assert data.loc[1, "citing"] == "OUTBOUND_B"
    assert data.loc[2, "cited_by"] == ""
    assert data.loc[2, "citing"] == ""


def test_add_citations_separate_deduplicates_relations(monkeypatch):
    data = pd.DataFrame({
        "celex": ["A"],
        # Same outbound URI repeated — must dedup to a single CELEX.
        "work_cites_work": ["http://uri/z;http://uri/z;http://uri/q"],
    })
    _patch_citation_sources(
        monkeypatch,
        uri_to_celex={
            "http://uri/z": "Z",
            "http://uri/q": "Q",
        },
        # Inbound rows also duplicated.
        get_cited_csv="celex,citedD\nA,X\nA,X\nA,Y\n",
    )

    citations_adder.add_citations_separate(data, threads=1)

    assert data.loc[0, "cited_by"] == "X;Y"
    assert data.loc[0, "citing"] == "Z;Q"


def test_add_citations_separate_handles_duplicate_input_celexes(monkeypatch):
    """Duplicate CELEXes in the input frame must get the same citing/cited_by
    values on every row carrying that CELEX. The new outbound path is row-
    scoped (each row's `work_cites_work` is resolved independently), so the
    citing value follows the row's own URI list rather than being shared."""
    data = pd.DataFrame({
        "celex": ["A", "A", "B"],
        "work_cites_work": [
            "http://uri/out_a",
            "http://uri/out_a",
            "",
        ],
    })
    _patch_citation_sources(
        monkeypatch,
        uri_to_celex={"http://uri/out_a": "X"},
        get_cited_csv="celex,citedD\nB,Y\n",
    )

    citations_adder.add_citations_separate(data, threads=3)

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
