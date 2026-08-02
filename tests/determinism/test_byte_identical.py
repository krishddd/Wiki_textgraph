"""The single most important CI gate (G1).

Build the graph twice from the same fixture corpus and assert the ``graph.json``
bytes are identical. Hash comparison, not diff-and-hope. This test grows in scope
as new layers land; it must stay green on every PR touching ``textgraph/``.
"""

from pathlib import Path

import pytest
from textgraph.core.content_address import blake3_hex
from textgraph.pipeline import build_graph_bytes

FIXTURES = Path(__file__).parent.parent / "fixtures"
FIXTURE_CORPUS = FIXTURES / "corpus_docs"
ALL_CORPORA = [FIXTURE_CORPUS, *sorted((FIXTURES / "corpora").iterdir())]


@pytest.mark.parametrize("corpus", ALL_CORPORA, ids=lambda p: p.name)
def test_graph_json_is_byte_identical_across_rebuilds(corpus: Path) -> None:
    first = build_graph_bytes(corpus)
    second = build_graph_bytes(corpus)
    assert blake3_hex(first) == blake3_hex(second)
    assert first == second


def test_graph_json_ends_with_single_newline() -> None:
    data = build_graph_bytes(FIXTURE_CORPUS)
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n")
