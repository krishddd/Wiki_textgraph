"""Jupyter integration — inline graph + citation-bearing tables (import-guarded deps)."""

from pathlib import Path

import pytest
from textgraph.notebook import TextGraph
from textgraph.pipeline import build

DOCS = str(Path(__file__).parent.parent / "fixtures" / "corpora" / "docs")


def _tg() -> TextGraph:
    return TextGraph(DOCS)


def test_show_embeds_the_self_contained_viewer() -> None:
    tg = _tg()
    out = tg.show()
    html = out if isinstance(out, str) else out.data
    assert "<iframe" in html and "sandbox=" in html  # sandboxed inline frame
    assert "__TG_DATA__" in html  # the offline viewer with embedded data, no server


def test_repr_html_is_a_summary_card_not_the_whole_graph() -> None:
    tg = _tg()
    card = tg._repr_html_()
    assert "TextGraph" in card and "entities" in card and "relations" in card
    assert "__TG_DATA__" not in card  # cheap summary; the heavy graph is only via .show()


def test_relations_table_carries_citations() -> None:
    rows = _tg().relations()
    assert isinstance(rows, list) or hasattr(rows, "columns")  # list or DataFrame
    as_list = rows if isinstance(rows, list) else rows.to_dict("records")
    assert as_list, "docs fixture has relations"
    r0 = as_list[0]
    assert {"source", "predicate", "target", "tag", "confidence", "citations"} <= set(r0)
    # A non-generated relation carries a re-verifiable [doc:start-end] citation.
    assert any("[" in r["citations"] for r in as_list)


def test_search_and_query_tables_have_expected_columns() -> None:
    tg = _tg()

    def _rows(x):
        return x if isinstance(x, list) else x.to_dict("records")

    s = _rows(tg.search("who transferred funds", k=5))
    assert s and "citations" in s[0] and "score" in s[0]
    e = _rows(tg.entities())
    assert e and "pagerank" in e[0] and "type" in e[0]
    w = _rows(tg.why("Acme Corp"))
    assert all("citations" in r for r in w)
    n = _rows(tg.neighbors("Acme Corp"))
    assert all("predicate" in r for r in n)


def test_roles_and_contradictions_tables() -> None:
    tg = _tg()

    def _rows(x):
        return x if isinstance(x, list) else x.to_dict("records")

    roles = _rows(tg.roles("Acme Corp"))
    assert all("similarity" in r for r in roles)


def test_from_engine_wraps_without_reloading() -> None:
    from textgraph.l8_retrieval import QueryEngine

    r = build(Path(DOCS))
    tg = TextGraph.from_engine(QueryEngine(r.nodes, r.edges))
    assert "TextGraph" in tg._repr_html_()
    assert tg.source == "<engine>"


def test_load_from_graph_json(tmp_path: Path) -> None:
    from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes

    r = build(Path(DOCS))
    gj = tmp_path / "graph.json"
    gj.write_bytes(
        dump_graph_bytes(
            build_graph_document(
                config_hash=r.config_hash, results=r.results, nodes=r.nodes, edges=r.edges
            )
        )
    )
    tg = TextGraph(gj)  # load, don't rebuild
    rows = tg.relations()
    as_list = rows if isinstance(rows, list) else rows.to_dict("records")
    assert as_list


def test_dataframe_path_when_pandas_present() -> None:
    pd = pytest.importorskip("pandas")
    df = _tg().relations()
    assert isinstance(df, pd.DataFrame)
    assert "citations" in df.columns
