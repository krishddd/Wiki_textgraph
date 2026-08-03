"""Phase 2: the build now produces a real knowledge graph (entities + relations),
still deterministic and with provenance on every non-generated edge."""

from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.content_address import verify_span_hash
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_pipeline_emits_entities_and_relations() -> None:
    result = build(DOCS)
    labels = {label for n in result.nodes for label in n.labels}
    preds = {e.predicate for e in result.edges}
    assert "Entity" in labels
    assert "Organization" in labels
    assert "TRANSFERRED" in preds
    assert result.ie_stats["entities"] > 0
    assert result.ie_stats["relations"] > 0


def test_all_four_confidence_tags_present_or_structural() -> None:
    result = build(DOCS)
    tags = {str(e.tag) for e in result.edges}
    assert "STRUCTURAL" in tags  # L1 spine
    assert "EXTRACTED" in tags  # L3 entities/relations
    # INFERRED appears when coref resolves a relation endpoint.
    assert "INFERRED" in tags


def test_ie_edges_carry_reverifiable_provenance() -> None:
    result = build(DOCS)
    raw_by_doc = {ir.doc_id: ir.raw for ir in result.results}
    ie_edges = [e for e in result.edges if str(e.tag) in ("EXTRACTED", "INFERRED")]
    assert ie_edges
    for e in ie_edges:
        for span in e.source_spans:
            assert verify_span_hash(raw_by_doc[span.doc_id], span.start, span.end, span.hash)


def test_structural_only_config_skips_ie() -> None:
    result = build(DOCS, config=Config(extract_ie=False))
    labels = {label for n in result.nodes for label in n.labels}
    assert "Entity" not in labels
    assert result.ie_stats.get("entities", 0) == 0
    assert result.ie_stats.get("relations", 0) == 0


def test_ie_build_is_byte_identical() -> None:
    from textgraph.pipeline import build_graph_bytes

    assert build_graph_bytes(DOCS) == build_graph_bytes(DOCS)
