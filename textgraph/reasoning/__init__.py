"""Deterministic rule reasoning (Datalog subset) over graph relations.

A forward-chaining engine that derives new relations from existing ones using recursive
IF/THEN rules — the classic ``ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z)`` shape — with a
full derivation trace for every inferred fact (explainable, no black box). Pure-Python and
byte-reproducible; derived facts are ``INFERRED`` suggestions surfaced at query time, never
written into ``graph.json`` (the determinism/provenance gates are untouched).
"""

from __future__ import annotations

from textgraph.reasoning.rules import (
    Derivation,
    Fact,
    Pattern,
    Rule,
    forward_chain,
    parse_rules,
)

__all__ = ["Derivation", "Fact", "Pattern", "Rule", "forward_chain", "parse_rules"]
