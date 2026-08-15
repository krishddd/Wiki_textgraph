"""Co-occurrence backbone (L6, opt-in) — STRUCTURAL edges between co-mentioned entities.

Verifies the edges are real, cited, deterministic, connect otherwise-orphan entities, and
are off by default (so the baseline determinism gate is untouched).
"""

from pathlib import Path

from textgraph.core.config import Config
from textgraph.l6_graph_model.cooccurrence import cooccurrence_edges
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"

_NON_RELATION = {"SAME_AS", "MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS"}


def test_off_by_default() -> None:
    r = build(DOCS)
    assert not [e for e in r.edges if e.predicate == "CO_OCCURS"]


def test_co_occurrence_adds_cited_structural_edges() -> None:
    r = build(DOCS, config=Config(co_occurrence=True))
    co = [e for e in r.edges if e.predicate == "CO_OCCURS"]
    assert co, "co-occurrence should link co-mentioned entities in this corpus"
    for e in co:
        assert str(e.tag) == "STRUCTURAL"
        assert e.source_spans, "every CO_OCCURS edge must cite the shared chunk"
        sp = e.source_spans[0]
        assert sp.end > sp.start and sp.hash  # a real, re-verifiable byte span
        assert e.subject.startswith("entity:") and e.object.startswith("entity:")
        assert e.subject < e.object  # canonical ordering (determinism)


def test_co_occurrence_reduces_orphans() -> None:
    base = build(DOCS)
    enriched = build(DOCS, config=Config(co_occurrence=True))

    def orphan_count(r: object) -> int:
        nodes = r.nodes
        edges = r.edges
        eids = {n.node_id for n in nodes if "Entity" in n.labels}
        deg = dict.fromkeys(eids, 0)
        for e in edges:
            if e.predicate in _NON_RELATION:
                continue
            if e.subject in deg:
                deg[e.subject] += 1
            if e.object in deg:
                deg[e.object] += 1
        return sum(1 for v in deg.values() if v == 0)

    assert orphan_count(enriched) < orphan_count(base)


def test_co_occurrence_is_deterministic() -> None:
    a = build(DOCS, config=Config(co_occurrence=True))
    b = build(DOCS, config=Config(co_occurrence=True))
    ea = sorted((e.subject, e.predicate, e.object) for e in a.edges if e.predicate == "CO_OCCURS")
    eb = sorted((e.subject, e.predicate, e.object) for e in b.edges if e.predicate == "CO_OCCURS")
    assert ea == eb and ea


def test_direct_helper_returns_sorted_unique() -> None:
    r = build(DOCS)  # a built graph provides results + nodes + MENTIONS edges
    edges = cooccurrence_edges(r.results, r.nodes, r.edges)
    ids = [e.edge_id for e in edges]
    assert ids == sorted(ids)  # sorted output (G1)
    assert len(ids) == len(set(ids))  # no duplicate edges
