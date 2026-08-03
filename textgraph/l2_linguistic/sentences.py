"""Deterministic sentence segmentation (L2).

A zero-model, abbreviation-aware splitter that returns canonical-char spans so
every sentence remains re-verifiable (G3). spaCy's statistical `senter` is a
higher-quality option available behind the ``[ie]`` extra, but the default path
must run without models (G2) and be byte-deterministic (G1).
"""

from __future__ import annotations

import re

from textgraph.core.layout import Span

# Abbreviations whose trailing period must not end a sentence. NOTE: org suffixes
# (Ltd/Inc/Corp/Co/LLC) are deliberately excluded — unlike titles, they routinely
# end a sentence ("...paid Beta Ltd. Acme then..."), and keeping them here produced
# run-on sentences that misattributed relation subjects.
_ABBREV = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "vs",
    "etc",
    "no",
    "fig",
    "eq",
    "al",
    "e.g",
    "i.e",
    "u.s",
    "u.k",
}
_BOUNDARY = re.compile(r"([.!?])[\)\"'”]?(\s+|\n+)")
_WORD_BEFORE = re.compile(r"([A-Za-z0-9.]+)$")


def segment(text: str, base: int = 0) -> list[Span]:
    """Split ``text`` into sentence spans, offset by ``base`` (canonical coords).

    Boundaries are `.?!` followed by whitespace, except after a known abbreviation
    or a single capital-letter initial. Deterministic and total: the whole input is
    covered by non-overlapping spans.
    """
    spans: list[Span] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        end = m.end(1)  # index just past the terminal punctuation
        prefix = text[start:end]
        wb = _WORD_BEFORE.search(text[:end].rstrip("."))
        token = wb.group(1).lower().rstrip(".") if wb else ""
        # Skip a boundary that follows an abbreviation or a single-letter initial.
        if token in _ABBREV or len(token) == 1:
            continue
        if prefix.strip():
            spans.append(Span(base + start, base + end))
        start = m.end()  # skip the trailing whitespace
    if start < len(text) and text[start:].strip():
        spans.append(Span(base + start, base + len(text.rstrip())))
    return spans
