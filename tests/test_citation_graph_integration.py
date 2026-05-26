import os

import pandas as pd
import pytest
from SPARQLWrapper import JSON, POST, SPARQLWrapper

from cellar_extractor.citations_adder import add_citations_separate
from cellar_extractor.nodes_and_edges import get_edges_list
from cellar_extractor.sparql import get_citations


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_CITATION_INTEGRATION") != "1",
    reason="Set RUN_CITATION_INTEGRATION=1 to run live citation graph tests.",
)

SAMPLE_CELEXES = ["62019CJ0668", "62019CJ0667", "62024CJ0131"]
ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"


def _normalize_relation(value):
    if pd.isna(value) or value == "":
        return set()
    return {part.strip() for part in str(value).split(";") if part.strip()}


def _raw_count_query(celex, relation):
    if relation == "outbound":
        body = """
            ?doc cdm:resource_legal_id_celex "%s"^^xsd:string .
            ?doc cdm:work_cites_work ?other .
        """ % celex
    else:
        body = """
            ?doc cdm:resource_legal_id_celex "%s"^^xsd:string .
            ?other cdm:work_cites_work ?doc .
        """ % celex

    query = """
        prefix cdm: <http://publications.europa.eu/ontology/cdm#>
        prefix xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT (COUNT(DISTINCT ?other) AS ?count) WHERE {
            %s
        }
    """ % body

    sparql = SPARQLWrapper(ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)
    sparql.setQuery(query)
    result = sparql.queryAndConvert()
    return int(result["results"]["bindings"][0]["count"]["value"])


@pytest.fixture(scope="module")
def citation_df():
    df = pd.DataFrame({"celex": SAMPLE_CELEXES})
    add_citations_separate(df, threads=1)
    return df


def test_live_citation_counts_match_independent_raw_sparql_counts(citation_df):
    for idx, celex in enumerate(SAMPLE_CELEXES):
        outbound = _normalize_relation(citation_df.loc[idx, "citing"])
        inbound = _normalize_relation(citation_df.loc[idx, "cited_by"])

        assert len(outbound) == _raw_count_query(celex, "outbound")
        assert len(inbound) == _raw_count_query(celex, "inbound")


def test_live_local_network_edges_match_inbound_lists(citation_df):
    sample_set = set(SAMPLE_CELEXES)
    outgoing = {
        celex: _normalize_relation(citation_df.loc[idx, "citing"])
        for idx, celex in enumerate(SAMPLE_CELEXES)
    }
    incoming = {
        celex: _normalize_relation(citation_df.loc[idx, "cited_by"])
        for idx, celex in enumerate(SAMPLE_CELEXES)
    }

    for source, targets in outgoing.items():
        for target in targets & sample_set:
            assert source in incoming[target]


def test_live_nodes_and_edges_counts_match_dataframe_relations(citation_df):
    global_edges, global_nodes = get_edges_list(citation_df, only_local=False)
    local_edges, local_nodes = get_edges_list(citation_df, only_local=True)

    expected_global_edges = set()
    expected_global_nodes = set(SAMPLE_CELEXES)
    expected_local_edges = set()
    for idx, source in enumerate(SAMPLE_CELEXES):
        for target in _normalize_relation(citation_df.loc[idx, "citing"]):
            expected_global_edges.add(f"{source},{target}")
            expected_global_nodes.add(target)
            if target in SAMPLE_CELEXES:
                expected_local_edges.add(f"{source},{target}")

    assert set(global_edges) == expected_global_edges
    assert set(global_nodes) == expected_global_nodes
    assert set(local_edges) == expected_local_edges
    assert set(local_nodes) == set(SAMPLE_CELEXES)


def test_live_local_edges_match_single_source_outbound_queries(citation_df):
    local_edges, _ = get_edges_list(citation_df, only_local=True)
    sample_set = set(SAMPLE_CELEXES)
    expected_edges = set()

    for source in SAMPLE_CELEXES:
        targets = get_citations(source, cites_depth=1, cited_depth=0)
        for target in targets & sample_set:
            expected_edges.add(f"{source},{target}")

    assert set(local_edges) == expected_edges


def test_live_duplicate_celex_rows_preserve_identical_citation_relations():
    duplicated = ["62019CJ0668", "62019CJ0668", "62024CJ0131"]
    df = pd.DataFrame({"celex": duplicated})

    add_citations_separate(df, threads=3)

    first_outbound = _normalize_relation(df.loc[0, "citing"])
    second_outbound = _normalize_relation(df.loc[1, "citing"])
    first_inbound = _normalize_relation(df.loc[0, "cited_by"])
    second_inbound = _normalize_relation(df.loc[1, "cited_by"])

    assert first_outbound == second_outbound
    assert first_inbound == second_inbound
    assert first_outbound == get_citations("62019CJ0668", cites_depth=1, cited_depth=0)
    assert first_inbound == get_citations("62019CJ0668", cites_depth=0, cited_depth=1)
