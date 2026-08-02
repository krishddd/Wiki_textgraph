"""Provenance-integrity gate for real L1 edges (G3).

Every non-GENERATED edge's source_spans must re-hash against the exact raw bytes of
the document they cite. This is the Phase 1 DoD requirement generalized from spans
to edges, run over every fixture corpus.
"""

from pathlib import Path

import pytest
from textgraph.core.content_address import verify_span_hash
from textgraph.pipeline import build

FIXTURES = Path(__file__).parent.parent / "fixtures"
CORPORA = [FIXTURES / "corpus_docs", *sorted((FIXTURES / "corpora").iterdir())]


@pytest.mark.parametrize("corpus", CORPORA, ids=lambda p: p.name)
def test_every_edge_span_reverifies(corpus: Path) -> None:
    result = build(corpus)
    raw_by_doc = {ir.doc_id: ir.raw for ir in result.results}
    assert result.edges, f"{corpus.name}: no edges built"

    checked = 0
    for edge in result.edges:
        assert str(edge.tag) != "GENERATED"  # nothing generated in the L0+L1 spine
        for span in edge.source_spans:
            raw = raw_by_doc[span.doc_id]
            assert verify_span_hash(raw, span.start, span.end, span.hash), (
                f"{corpus.name}: edge {edge.predicate} span failed re-verification"
            )
            checked += 1
    assert checked > 0
