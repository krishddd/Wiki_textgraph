"""L6 claim reification: relation edges become citable Claim nodes."""

from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.content_address import verify_span_hash
from textgraph.l6_graph_model import claim_id_for, reify_claims
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
TEMPORAL = Path(__file__).parent.parent / "fixtures" / "corpora" / "temporal"


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


def _claims_by_polarity(nodes: list, predicate: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for n in nodes:
        p = n.properties
        if "Claim" in n.labels and p["predicate"] == predicate:
            out[str(p["polarity"])] = p
    return out


def test_later_correction_supersedes_and_closes_the_window() -> None:
    # "transferred (2026-05-01)" then "did not transfer (2026-06-01)" — the later,
    # opposite-polarity claim invalidates the earlier one (invalidation, not deletion).
    result = build(TEMPORAL)
    claims = _claims_by_polarity(result.nodes, "TRANSFERRED")
    assert claims["pos"]["t_valid"] == "2026-05-01"
    assert claims["pos"]["t_invalid"] == "2026-06-01"  # closed by the correction
    assert claims["neg"]["t_valid"] == "2026-06-01"
    assert claims["neg"]["t_invalid"] is None  # the current belief stays open


def test_supersedes_edge_is_emitted_and_cited() -> None:
    result = build(TEMPORAL)
    sup = [e for e in result.edges if e.predicate == "SUPERSEDES"]
    assert len(sup) == 1
    e = sup[0]
    assert e.subject.startswith("claim:") and e.object.startswith("claim:")
    assert str(e.tag) == "INFERRED"
    assert e.source_spans  # the correcting assertion cites real bytes
    raw = {ir.doc_id: ir.raw for ir in result.results}
    for s in e.source_spans:
        assert verify_span_hash(raw[s.doc_id], s.start, s.end, s.hash)


def test_invalidation_can_be_disabled() -> None:
    result = build(TEMPORAL, config=Config(invalidate_claims=False))
    assert not [e for e in result.edges if e.predicate == "SUPERSEDES"]
    assert all(n.properties.get("t_invalid") is None for n in result.nodes if "Claim" in n.labels)


def test_undated_conflict_is_not_superseded() -> None:
    # The contradiction fixture dates only the positive claim, so the two can't be
    # ordered in time — no wall-clock guess, no SUPERSEDES (G1). The conflict still
    # surfaces via L7's CONTRADICTS.
    contra = Path(__file__).parent.parent / "fixtures" / "corpora" / "contradiction"
    result = build(contra)
    assert not [e for e in result.edges if e.predicate == "SUPERSEDES"]
    assert [e for e in result.edges if e.predicate == "CONTRADICTS"]
