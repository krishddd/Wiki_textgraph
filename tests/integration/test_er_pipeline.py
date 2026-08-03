"""Phase 3 DoD: alias entities resolve reversibly; blocking recall ≥0.99;
B-cubed F1 above a pinned floor; the god-node diagnostic flags an over-merge."""

from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.content_address import verify_span_hash
from textgraph.l5_entity_resolution import (
    bcubed,
    blocking_recall,
    build_records,
    emit_er,
    run_er,
)
from textgraph.l5_entity_resolution.blocking import candidate_pairs
from textgraph.l5_entity_resolution.model import ERecord
from textgraph.l5_entity_resolution.similarity import acronym
from textgraph.l9_artifacts import analytics_lite
from textgraph.pipeline import build
from textgraph.store.base import SourceSpan

_FAKE_SPAN = SourceSpan(doc_id="blake3:x", start=0, end=1, hash="00")

ER = Path(__file__).parent.parent / "fixtures" / "er"

# Gold clustering for the aliases fixture (Acme variants together; others singletons).
GOLD = {
    "entity:Organization:acme": "acme",
    "entity:Organization:acme corp": "acme",
    "entity:Organization:acme corporation": "acme",
    "entity:Organization:beta ltd": "beta",
    "entity:Organization:beta limited": "beta",
    "entity:Organization:gamma holdings": "gamma",
    "entity:Organization:alpha bank": "alpha",
}


def _records():
    result = build(ER)
    return result, build_records(result.nodes, result.edges)


def test_aliases_collapse_to_canonical() -> None:
    _result, records = _records()
    er = run_er(records)
    by_canon = {c.canonical_id: set(c.members) for c in er.clusters}
    acme = {
        "entity:Organization:acme",
        "entity:Organization:acme corp",
        "entity:Organization:acme corporation",
    }
    assert any(acme <= members for members in by_canon.values())
    # Alpha Bank must NOT be swept into the Acme cluster.
    for members in by_canon.values():
        if "entity:Organization:alpha bank" in members:
            assert members == {"entity:Organization:alpha bank"}


def test_resolution_is_non_destructive() -> None:
    result, _ = _records()
    # Original entity nodes are preserved alongside the new canonical node.
    ids = {n.node_id for n in result.nodes}
    assert "entity:Organization:acme corp" in ids
    assert any("Canonical" in n.labels for n in result.nodes)


def test_blocking_recall_meets_floor() -> None:
    _result, records = _records()
    pairs = candidate_pairs(records)
    gold = {k: v for k, v in GOLD.items() if k in {r.entity_id for r in records}}
    assert blocking_recall(pairs, gold) >= 0.99


def test_bcubed_f1_above_floor() -> None:
    _result, records = _records()
    er = run_er(records)
    member_to_canon = {m: c.canonical_id for c in er.clusters for m in c.members}
    pred = {r.entity_id: member_to_canon.get(r.entity_id, r.entity_id) for r in records}
    gold = {k: v for k, v in GOLD.items() if k in pred}
    _p, _r, f1 = bcubed(pred, gold)
    assert f1 >= 0.9  # pinned floor


def test_same_as_edges_have_provenance() -> None:
    result, records = _records()
    er = run_er(records)
    _nodes, edges = emit_er(er)
    raw_by_doc = {ir.doc_id: ir.raw for ir in result.results}
    assert edges
    for e in edges:
        assert str(e.tag) == "INFERRED"
        for span in e.source_spans:
            assert verify_span_hash(raw_by_doc[span.doc_id], span.start, span.end, span.hash)


def test_god_node_flags_injected_over_merge() -> None:
    # Inject many aliases that all resolve to one canonical -> high-degree god node.
    recs = [
        ERecord(
            entity_id=f"entity:Organization:acme {sfx}",
            name=f"Acme {sfx.title()}",
            etype="Organization",
            norm=f"acme {sfx}",
            stripped="acme",
            acronym=acronym(f"Acme {sfx}"),
            mention_spans=(_FAKE_SPAN,),
        )
        for sfx in ("corp", "ltd", "inc", "group", "trust", "fund", "holdings")
    ]
    er = run_er(recs)
    nodes, edges = emit_er(er)
    diag = analytics_lite.compute(nodes, edges)
    canonical_ids = {n.node_id for n in nodes if "Canonical" in n.labels}
    assert canonical_ids
    god_ids = {nid for nid, _deg in diag.god_nodes}
    assert canonical_ids & god_ids  # the over-merged canonical is flagged


def test_er_build_is_deterministic() -> None:
    from textgraph.pipeline import build_graph_bytes

    assert build_graph_bytes(ER) == build_graph_bytes(ER)


def test_structural_only_skips_er() -> None:
    result = build(ER, config=Config(resolve_entities=False))
    assert not any("Canonical" in n.labels for n in result.nodes)
    assert result.er_stats == {}
