"""L6 claim reification: relation edges become citable Claim nodes."""

from pathlib import Path

from textgraph.core.content_address import verify_span_hash
from textgraph.l6_graph_model import claim_id_for, reify_claims
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_each_relation_edge_is_reified_into_a_claim() -> None:
    result = build(DOCS)
    claims = [n for n in result.nodes if "Claim" in n.labels]
    relations = [
        e
        for e in result.edges
        if e.subject.startswith("entity:")
        and e.object.startswith("entity:")
        and e.predicate not in ("SAME_AS", "MENTIONS", "SUBJECT_OF", "HAS_OBJECT", "CONTRADICTS")
    ]
    assert claims
    # One claim per distinct reified relation edge (dedup on the claim id).
    assert len(claims) == len({claim_id_for(e) for e in relations})


def test_claims_carry_full_assertion_fields() -> None:
    result = build(DOCS)
    for n in result.nodes:
        if "Claim" not in n.labels:
            continue
        p = n.properties
        assert p["subject"] and p["predicate"] and p["object"]
        assert p["polarity"] in ("pos", "neg")
        assert "t_valid" in p and "t_invalid" in p


def test_reified_edges_reverify_against_raw_bytes() -> None:
    result = build(DOCS)
    raw_by_doc = {ir.doc_id: ir.raw for ir in result.results}
    reified = [e for e in result.edges if e.predicate in ("SUBJECT_OF", "HAS_OBJECT")]
    assert reified
    for e in reified:
        for span in e.source_spans:
            assert verify_span_hash(raw_by_doc[span.doc_id], span.start, span.end, span.hash)


def test_claim_id_is_stable() -> None:
    result = build(DOCS)
    claim_nodes, _ = reify_claims(result.nodes, result.edges)
    again, _ = reify_claims(result.nodes, result.edges)
    assert [n.node_id for n in claim_nodes] == [n.node_id for n in again]


def test_temporal_grounding_from_nearby_date() -> None:
    # The docs fixture states "Acme Corp ... on 2026-07-30"; the reified claim about
    # that transfer should pick up the date as t_valid.
    result = build(DOCS)
    transfers = [
        n
        for n in result.nodes
        if "Claim" in n.labels and n.properties["predicate"] == "TRANSFERRED"
    ]
    assert any(n.properties["t_valid"] for n in transfers)
