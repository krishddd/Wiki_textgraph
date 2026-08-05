"""Phase 7: GQL parser + engine, and round-trip against the graph the tools query."""

from pathlib import Path

import pytest
from textgraph.gql import GQLEngine, GQLError, parse
from textgraph.gql.ast import PathPattern, RelPattern
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
CONTRA = Path(__file__).parent.parent / "fixtures" / "corpora" / "contradiction"


def _engine(corpus: Path = DOCS) -> GQLEngine:
    r = build(corpus)
    return GQLEngine(r.nodes, r.edges)


# -- parser -----------------------------------------------------------------------


def test_parse_basic_pattern() -> None:
    q = parse("MATCH (a:Entity {name:'Acme'})-[r:CONTROLS]->(b) RETURN a.name, type(r)")
    assert isinstance(q.pattern, PathPattern)
    assert q.pattern.nodes[0].labels == ("Entity",)
    assert q.pattern.nodes[0].props == (("name", "Acme"),)
    assert q.pattern.rels[0].types == ("CONTROLS",)
    assert q.pattern.rels[0].direction == "out"
    assert len(q.returns) == 2  # a.name, type(r)


def test_parse_quantified_path_and_directions() -> None:
    q = parse("MATCH (a)-[:R*2..4]->(b) RETURN b")
    rel: RelPattern = q.pattern.rels[0]
    assert (rel.min_hops, rel.max_hops) == (2, 4)
    assert parse("MATCH (a)<-[:R]-(b) RETURN b").pattern.rels[0].direction == "in"
    assert parse("MATCH (a)-[:R]-(b) RETURN b").pattern.rels[0].direction == "both"


def test_parse_errors_are_positioned() -> None:
    with pytest.raises(GQLError):
        parse("MATCH (a)-[:R]->(b)")  # no RETURN
    with pytest.raises(GQLError):
        parse("MATCH (a RETURN a")  # unclosed node
    with pytest.raises(GQLError):
        parse("MATCH (a)<-[:R]->(b) RETURN a")  # both directions


# -- engine -----------------------------------------------------------------------


def test_match_labels_props_and_direction() -> None:
    g = _engine()
    rows = g.query(
        "MATCH (a:Organization {name:'Acme Corp'})-[r]->(b:Entity) RETURN b.name, type(r)"
    ).rows
    got = {(name, typ) for name, typ in rows}
    assert ("Gamma Holdings", "CONTROLS") in got
    assert ("Beta Ltd", "TRANSFERRED") in got


def test_where_and_contains_and_boolean() -> None:
    g = _engine()
    rows = g.query(
        "MATCH (a:Entity)-[r]->(b:Entity) "
        "WHERE a.name CONTAINS 'Acme' AND type(r) = 'CONTROLS' RETURN b.name"
    ).rows
    assert rows == [["Gamma Holdings"]]


def test_count_aggregation_and_order() -> None:
    g = _engine()
    res = g.query("MATCH (n:Entity) RETURN n.etype, count(*) AS c ORDER BY c DESC")
    assert res.columns == ["n.etype", "c"]
    assert res.rows[0] == ["Organization", 6]  # most common etype first


def test_quantified_path_reaches_target() -> None:
    g = _engine()
    rows = g.query(
        "MATCH (a {name:'Acme Corp'})-[*1..3]->(b {name:'Gamma Holdings'}) RETURN b.name"
    ).rows
    assert rows and all(r == ["Gamma Holdings"] for r in rows)


def test_distinct_and_limit() -> None:
    g = _engine()
    all_rows = g.query("MATCH (a {name:'Acme Corp'})-[*1..3]->(b) RETURN DISTINCT b.name").rows
    limited = g.query("MATCH (n:Entity) RETURN n.name ORDER BY n.name LIMIT 2").rows
    assert len(limited) == 2
    assert len(all_rows) == len({tuple(r) for r in all_rows})  # DISTINCT deduped


def test_engine_is_deterministic() -> None:
    g = _engine()
    a = g.query("MATCH (a:Entity)-[r]->(b:Entity) RETURN a.name, type(r), b.name").rows
    b = g.query("MATCH (a:Entity)-[r]->(b:Entity) RETURN a.name, type(r), b.name").rows
    assert a == b


# -- round-trip DoD: pattern-based tools expressed as GQL match the graph ---------


def test_roundtrip_neighbors_matches_relation_edges() -> None:
    r = build(DOCS)
    gql = GQLEngine(r.nodes, r.edges)
    # GQL out-neighbours of Acme via any relation.
    got = {
        (typ, name)
        for name, typ in gql.query(
            "MATCH (a:Entity {name:'Acme Corp'})-[r]->(b:Entity) RETURN b.name, type(r)"
        ).rows
    }
    # The same, read straight off the relation edges.
    acme = next(n.node_id for n in r.nodes if n.properties.get("name") == "Acme Corp")
    names = {n.node_id: n.properties.get("name") for n in r.nodes}
    plumbing = {"MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "SAME_AS"}
    expected = {
        (e.predicate, names[e.object])
        for e in r.edges
        if e.subject == acme and e.object in names and e.predicate not in plumbing
    }
    assert got == expected


def test_roundtrip_path_matches_query_engine() -> None:
    r = build(DOCS)
    gql = GQLEngine(r.nodes, r.edges)
    qe = QueryEngine(r.nodes, r.edges)
    reached = bool(
        gql.query("MATCH (a {name:'Acme Corp'})-[*1..4]-(b {name:'John Doe'}) RETURN b.name").rows
    )
    tool = bool(qe.path("Acme Corp", "John Doe", k=1).paths)
    assert reached == tool is True


def test_roundtrip_contradictions_via_pattern() -> None:
    r = build(CONTRA)
    gql = GQLEngine(r.nodes, r.edges)
    qe = QueryEngine(r.nodes, r.edges)
    gql_pairs = gql.query("MATCH (a:Claim)-[:CONTRADICTS]->(b:Claim) RETURN a.predicate").rows
    assert len(gql_pairs) == len(qe.contradictions().pairs) >= 1


# -- operators / functions / clauses ----------------------------------------------


def test_numeric_comparison_operators() -> None:
    g = _engine()
    # PageRank is a float property on entities; exercise > >= < and NOT/OR.
    hi = g.query("MATCH (n:Entity) WHERE n.pagerank > 0.1 RETURN n.name").rows
    lo = g.query("MATCH (n:Entity) WHERE NOT n.pagerank >= 0.1 RETURN n.name").rows
    both = g.query(
        "MATCH (n:Entity) WHERE n.pagerank < 0.01 OR n.pagerank > 0.2 RETURN n.name"
    ).rows
    assert hi and lo and isinstance(both, list)
    assert {tuple(r) for r in hi}.isdisjoint({tuple(r) for r in lo})


def test_string_operators_and_inequality() -> None:
    g = _engine()
    assert g.query("MATCH (n:Organization) WHERE n.name STARTS WITH 'Acme' RETURN n.name").rows == [
        ["Acme Corp"]
    ]
    ends = g.query("MATCH (n:Organization) WHERE n.name ENDS WITH 'Ltd' RETURN n.name").rows
    assert ["Beta Ltd"] in ends
    ne = g.query("MATCH (n:Organization) WHERE n.etype <> 'Person' RETURN n.name").rows
    assert ne


def test_id_and_labels_functions_and_skip() -> None:
    g = _engine()
    rows = g.query("MATCH (n:Organization {name:'Acme Corp'}) RETURN id(n), labels(n)").rows
    assert rows[0][0].startswith("entity:")
    assert "Entity" in rows[0][1] and "Organization" in rows[0][1]
    # SKIP + ORDER BY ... ASC over a bare property.
    ordered = g.query("MATCH (n:Organization) RETURN n.name ORDER BY n.name SKIP 1").rows
    assert ordered == sorted(ordered)


def test_execution_errors_raise_gqlerror() -> None:
    g = _engine()
    with pytest.raises(GQLError):  # ORDER BY a column that isn't returned
        g.query("MATCH (n:Entity) RETURN n.name ORDER BY n.etype")
    with pytest.raises(GQLError):  # unterminated string
        g.query("MATCH (n {name:'oops}) RETURN n")


def test_cli_gql_command(capsys: pytest.CaptureFixture[str]) -> None:
    from textgraph.cli import main

    rc = main(["gql", str(DOCS), "MATCH (a:Organization)-[:CONTROLS]->(b) RETURN a.name, b.name"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Acme Corp | Gamma Holdings" in out
    assert "(1 row)" in out
