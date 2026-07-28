import pandas as pd

from cellar_extractor import cellar
from cellar_extractor import nodes_and_edges


def test_get_edges_list_returns_all_outbound_edges():
    df = pd.DataFrame(
        {
            "celex": ["A", "B", "C"],
            "citing": ["B;C", "C", ""],
        }
    )

    edges, nodes = nodes_and_edges.get_edges_list(df, only_local=False)

    assert edges == ["A,B", "A,C", "B,C"]
    assert nodes == ["A", "B", "C"]


def test_get_edges_list_only_local_filters_external_targets():
    df = pd.DataFrame(
        {
            "celex": ["A", "B"],
            "citing": ["B;EXT", ""],
        }
    )

    edges, nodes = nodes_and_edges.get_edges_list(df, only_local=True)

    assert edges == ["A,B"]
    assert nodes == ["A", "B"]


def test_get_nodes_and_edges_lists_delegates_cleanly():
    df = pd.DataFrame(
        {
            "celex": ["A", "B"],
            "citing": ["B", ""],
        }
    )

    nodes, edges = cellar.get_nodes_and_edges_lists(df=df, only_local=True)

    assert nodes == ["A", "B"]
    assert edges == ["A,B"]
