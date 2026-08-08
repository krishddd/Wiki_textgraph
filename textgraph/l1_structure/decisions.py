"""Decision objects — a queryable causal layer over the L1 ``Rationale`` spine.

TextGraph's L1 pass already extracts ``Rationale`` markers (``WHY``/``DECISION``/
``RATIONALE``/``ADR-N``) with byte-span citations. This module promotes the
*decision-worthy* ones into first-class ``Decision`` nodes and links them with a
narrow, agent-legible set of **causal** edges — the shape the "decision provenance"
literature (Singh/Cobbe/Norval) and defensible AML case files both call for:
**inputs -> decision -> downstream effects**.

Design constraints:

* **Derived, not re-extracted.** A ``Decision`` is built from an existing ``Rationale``
  node and *reuses that rationale's exact ``SourceSpan``*, so every emitted edge still
  re-hashes against the raw bytes (G3) and nothing is tagged ``GENERATED``.
* **Narrow causal vocabulary.** Only three causal predicates — ``CAUSED``,
  ``INFLUENCED``, ``PRECEDENT_FOR`` — mirroring the constrained enum that keeps the
  graph legible (G6). Causality is author-controlled: it comes from an explicit
  in-text reference to another ADR (e.g. ``DECISION: ... SUPERSEDES ADR-0007``).
* **Deterministic.** Content-addressed ids, sorted output, pure function of (nodes,
  edges) — byte-identical across runs (G1).

Automated ancestry traversal (``trace_decision_chain``) and similarity search
(``find_similar_decisions``) are deliberately out of scope here: they depend on L6/L8
and layer on later. This module ships the node type + causal edges, which are cheap,
high-value, and dependency-free.
"""

from __future__ import annotations

import re

from textgraph.core.content_address import hash_text
from textgraph.l1_structure.emit import edge, node
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

# Markers that denote an actual decision (not a TODO/NOTE/CONTEXT aside).
_DECISION_WORDS = frozenset({"WHY", "DECISION", "RATIONALE"})
# An ADR marker, e.g. "ADR-0007" or "ADR- 7" — the whole record is one decision.
_ADR_MARK = re.compile(r"^ADR[- ]?(\d+)$", re.IGNORECASE)
# An in-text reference to another ADR, optionally led by a causal keyword.
_ADR_REF = re.compile(
    r"\b(SUPERSEDES?|REPLACES?|DEPRECATES?|AMENDS?|PRECEDENT(?:[- ]FOR)?"
    r"|CAUSED[- ]BY|BECAUSE\s+OF|DUE\s+TO|RESULT\s+OF|INFLUENCED[- ]BY|BUILDS\s+ON)?"
    r"\s*\bADR[- ]?(\d+)\b",
    re.IGNORECASE,
)


def _causal_predicate(keyword: str) -> str:
    """Map an in-text keyword to one of the three causal predicates."""
    k = keyword.upper().replace("-", " ").strip()
    if k.startswith(("SUPERSEDE", "REPLACE", "DEPRECATE", "AMEND", "PRECEDENT")):
        return "PRECEDENT_FOR"
    if k.startswith(("CAUSED", "BECAUSE", "DUE", "RESULT")):
        return "CAUSED"
    return "INFLUENCED"  # "influenced by", "builds on", or a bare mention


def _category(marker: str, name: str) -> tuple[str, int | None]:
    """Classify a rationale marker -> (category, adr_number). Non-decisions -> ("", None).

    ``name`` is the rationale's line text, used to tell an ADR *record* (the heading
    ``# ADR-0007: ...``, which leads its line) from a mere ADR *reference* embedded in
    some other decision (``DECISION: ... supersedes ADR-0007``). Only the record becomes
    an ``adr`` Decision; the reference is left for the causal-linking pass to consume.
    """
    text = marker.strip().rstrip(":").strip()
    m = _ADR_MARK.match(text)
    if m:
        head = name.lstrip("#").strip().upper()
        if head.startswith(text.upper()):  # leads the line -> a record, not a reference
            return "adr", int(m.group(1))
        return "", None
    up = text.upper()
    if up in _DECISION_WORDS:
        return up.lower(), None
    return "", None


def derive_decisions(nodes: list[Node], edges: list[Edge]) -> tuple[list[Node], list[Edge]]:
    """Promote decision-worthy ``Rationale`` nodes into ``Decision`` nodes + causal edges.

    Returns ``(decision_nodes, decision_edges)`` in deterministic (id-sorted) order. The
    caller merges these into the graph; ids are content-addressed so re-merging is a no-op.
    """
    rationales = {n.node_id: n for n in nodes if "Rationale" in n.labels}
    if not rationales:
        return [], []

    # Each rationale's citing span + the block it applies to (from its APPLIES_TO edge).
    span_of: dict[str, SourceSpan] = {}
    for e in edges:
        if e.predicate == "APPLIES_TO" and e.subject in rationales and e.source_spans:
            span_of.setdefault(e.subject, e.source_spans[0])

    out_nodes: dict[str, Node] = {}
    out_edges: dict[str, Edge] = {}
    # decision_id keyed by ADR number, so an in-text "ADR-7" reference can find its target.
    adr_index: dict[int, str] = {}
    # (referencing decision_id, statement, span) collected for a second causal-linking pass.
    pending: list[tuple[str, str, SourceSpan]] = []

    for rid, rnode in sorted(rationales.items()):
        span = span_of.get(rid)
        if span is None:  # a rationale with no citing edge can't be provenanced — skip
            continue
        marker = str(rnode.properties.get("marker", ""))
        statement = str(rnode.properties.get("name", ""))
        category, adr_num = _category(marker, statement)
        if not category:
            continue
        did = "decision:" + hash_text(rid)
        out_nodes[did] = node(
            did,
            "Decision",
            statement,
            category=category,
            marker=marker,
            statement=statement,
            doc_id=span.doc_id,
        )
        # Provenance link back to the rationale it was derived from (reuses the valid span).
        e = edge(did, "DERIVED_FROM", rid, span, tag=ConfidenceTag.INFERRED, confidence=0.9)
        out_edges[e.edge_id] = e
        if adr_num is not None:
            adr_index.setdefault(adr_num, did)
        pending.append((did, statement, span))

    # Second pass: causal edges from in-text ADR references (needs the full adr_index).
    for did, statement, span in pending:
        for keyword, num_str in _ADR_REF.findall(statement):
            target = adr_index.get(int(num_str))
            if target is None or target == did:  # unknown ADR or a self-reference
                continue
            predicate = _causal_predicate(keyword)
            # The referenced (usually prior) decision is the source; this one is the object.
            e = edge(target, predicate, did, span, tag=ConfidenceTag.INFERRED, confidence=0.8)
            out_edges[e.edge_id] = e

    nodes_sorted = sorted(out_nodes.values(), key=lambda n: n.node_id)
    edges_sorted = sorted(out_edges.values(), key=lambda e: e.edge_id)
    return nodes_sorted, edges_sorted
