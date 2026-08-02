"""L1 — Deterministic Structure Parse.

Zero-model extraction of the structural spine: sections, links, definitions,
citations, cross-references, rationale/requirement nodes, transcript threads, log
templates, and structured fields. Every edge is STRUCTURAL with a re-verifiable
span. See ARCHITECTURE.md.
"""

from textgraph.l1_structure.structure import parse_corpus

__all__ = ["parse_corpus"]
