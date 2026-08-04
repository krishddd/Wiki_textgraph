"""L6 — bi-temporal assembly: invalidation, not deletion (Phase 5).

Once relations are reified into :class:`Claim` nodes (see :mod:`.claims`), this
module closes their validity windows. When two claims about the *same*
``(subject, predicate, object)`` disagree in polarity, the one asserted later
supersedes the earlier: the earlier claim's ``t_invalid`` is set to the later claim's
``t_valid``, and a ``SUPERSEDES`` edge records the correction. Nothing is deleted —
"X paid Y" stays in the graph with a closed window, so an agent can still ask *what
was believed true, and when it changed* (§8, bi-temporal).

The ordering source is deliberately **valid-time stated in the text** (`t_valid`, an
in-corpus date), compared lexically — ISO dates sort chronologically. There is no
wall-clock anywhere (G1): a claim with no in-text date cannot be ordered, so it is
left open rather than invalidated by a guess. The conflict is still surfaced via the
L7 ``CONTRADICTS`` edge; ``SUPERSEDES`` is only emitted when the corpus itself dates
the correction.
"""

from __future__ import annotations

from dataclasses import replace

from textgraph.core.content_address import hash_text
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan


def _claim_spans(claim_edges: list[Edge]) -> dict[str, tuple[SourceSpan, ...]]:
    """claim_id -> its citing spans (from the reified SUBJECT_OF / HAS_OBJECT edges)."""
    spans: dict[str, tuple[SourceSpan, ...]] = {}
    for e in claim_edges:
        if e.predicate == "SUBJECT_OF" and e.object.startswith("claim:"):
            spans.setdefault(e.object, e.source_spans)
        elif e.predicate == "HAS_OBJECT" and e.subject.startswith("claim:"):
            spans.setdefault(e.subject, e.source_spans)
    return spans


def _triple(n: Node) -> tuple[str, str, str]:
    p = n.properties
    return (str(p.get("subject", "")), str(p.get("predicate", "")), str(p.get("object", "")))


def apply_temporal(
    claim_nodes: list[Node], claim_edges: list[Edge]
) -> tuple[list[Node], list[Edge]]:
    """Close validity windows across contradicting claims + emit ``SUPERSEDES`` edges.

    Returns ``(updated_claim_nodes, supersedes_edges)``. A claim keeps its identity;
    only its ``t_invalid`` may change. Deterministic: grouping and ordering are by
    sorted keys and lexical dates.
    """
    spans = _claim_spans(claim_edges)
    groups: dict[tuple[str, str, str], list[Node]] = {}
    for n in claim_nodes:
        groups.setdefault(_triple(n), []).append(n)

    invalidated: dict[str, str] = {}  # claim_id -> t_invalid date
    supersedes: dict[str, Edge] = {}
    for members in groups.values():
        # Only dated claims can be ordered in time (no wall-clock fallback, G1).
        dated = sorted(
            (n for n in members if n.properties.get("t_valid")),
            key=lambda n: (str(n.properties["t_valid"]), n.node_id),
        )
        for i, claim in enumerate(dated):
            polarity = claim.properties.get("polarity", "pos")
            # First strictly-later claim that flips polarity closes this one's window.
            for later in dated[i + 1 :]:
                if str(later.properties["t_valid"]) <= str(claim.properties["t_valid"]):
                    continue
                if later.properties.get("polarity", "pos") == polarity:
                    continue
                invalidated[claim.node_id] = str(later.properties["t_valid"])
                edge = Edge(
                    edge_id="edge:" + hash_text(f"{later.node_id}|SUPERSEDES|{claim.node_id}"),
                    subject=later.node_id,
                    predicate="SUPERSEDES",
                    object=claim.node_id,
                    tag=ConfidenceTag.INFERRED,
                    confidence=float(later.properties.get("confidence", 0.0)),
                    evidence_count=len(spans.get(later.node_id, ())),
                    source_spans=spans.get(later.node_id, ()),
                    properties={"invalidated_at": str(later.properties["t_valid"])},
                )
                supersedes.setdefault(edge.edge_id, edge)
                break

    updated: list[Node] = []
    for n in claim_nodes:
        if n.node_id in invalidated:
            props = dict(n.properties)
            props["t_invalid"] = invalidated[n.node_id]
            updated.append(replace(n, properties=props))
        else:
            updated.append(n)

    nodes_out = sorted(updated, key=lambda n: n.node_id)
    edges_out = sorted(supersedes.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out
