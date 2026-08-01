"""Provenance-integrity gate (G3).

For the fixture corpus, exercise the full span citation path: pick spans in each
canonical doc, record their byte-range hash, then re-resolve against the original
bytes and assert the hash still matches. When real edges exist (Phase 1+), this
generalizes to "every non-GENERATED edge's source_spans re-verify."
"""

from pathlib import Path

import pytest
from textgraph.core.canonical_doc import CanonicalDoc
from textgraph.core.content_address import verify_span_hash

FIXTURE_CORPUS = Path(__file__).parent.parent / "fixtures" / "corpus_docs"


@pytest.mark.parametrize("path", sorted(FIXTURE_CORPUS.glob("*")))
def test_every_span_rehashes_against_source(path: Path) -> None:
    raw = path.read_bytes()
    doc = CanonicalDoc.from_bytes(raw, source_name=path.name)
    text_len = len(doc.text)

    # A spread of spans across the document, including boundary and full-doc.
    spans = {(0, 0), (0, text_len)}
    if text_len >= 2:
        spans.add((0, text_len // 2))
        spans.add((text_len // 2, text_len))
        spans.add((1, text_len - 1))

    for start, end in spans:
        b0, b1 = doc.raw_span(start, end)
        span_hash = doc.span_hash(raw, start, end)
        assert verify_span_hash(raw, b0, b1, span_hash), (
            f"span [{start},{end}) in {path.name} failed re-verification"
        )
