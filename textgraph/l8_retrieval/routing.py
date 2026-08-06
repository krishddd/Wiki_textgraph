"""Per-query retrieval routing (deterministic).

Not every question wants the same retrieval strategy. A relational question ("how is X
connected to Y") wants **graph traversal**; a lookup ("who is X") wants **entity + lexical
search**; a structured query (``MATCH …``) wants the **GQL** engine; an open question ("who
moved the money") wants the **hybrid** BM25 + Personalized-PageRank walk. This module makes
that decision explicit and testable: :func:`classify_query` maps a question to a *tool*, and
:func:`route` wraps that in a :class:`RoutePlan` that also names the retrieval *strategy
family* and a short human reason.

The rules are pure, ordered, and deterministic (no model, no clock), so routing is
reproducible (G1) and auditable (G6) — the plan can be shown to the user. It is the single
source of truth the console "Ask" chat and any agent share, so routing never drifts between
surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass

# The tools a query can route to (also the chat's chips / an agent's action space).
TOOLS = (
    "auto",
    "reason",
    "search",
    "path",
    "why",
    "neighbors",
    "timeline",
    "contradictions",
    "communities",
    "stats",
    "gql",
)

# Which retrieval *strategy family* each tool belongs to — the "graph traversal vs vector vs
# keyword vs hybrid" axis the routing is really choosing between.
STRATEGY: dict[str, str] = {
    "gql": "structured-graph",  # declarative pattern match over the property graph
    "path": "graph-traversal",  # multi-hop max-likelihood path
    "neighbors": "graph-traversal",  # one-hop expansion
    "why": "graph-traversal",  # claim neighbourhood of one node
    "timeline": "graph-traversal",  # temporal slice of one node
    "contradictions": "graph-analytics",  # precomputed CONTRADICTS edges
    "communities": "graph-analytics",  # precomputed clusters
    "stats": "graph-analytics",  # aggregate counts
    "search": "hybrid-lexical-graph",  # BM25 + Personalized PageRank + RRF
    "reason": "hybrid-multi-tool",  # Graph-of-Thoughts over several of the above
}

# Ordered cue → tool rules. First match wins; documented so the decision is auditable.
_PATH_CUES = (
    "connected to",
    "connects to",
    "linked to",
    "link between",
    "path from",
    "path between",
    "between ",
)


@dataclass(frozen=True)
class RoutePlan:
    """The routing decision for one query: which tool, which strategy family, and why."""

    tool: str
    strategy: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"tool": self.tool, "strategy": self.strategy, "reason": self.reason}


def classify_query(question: str, forced: str = "auto") -> str:
    """Deterministically pick the retrieval *tool* for a question (or honour an override)."""
    if forced and forced != "auto":
        return forced if forced in TOOLS else "reason"
    low = question.lower().strip()
    if low.startswith("match ") or " return " in low:
        return "gql"
    if any(cue in low for cue in _PATH_CUES):
        return "path"
    if low.startswith("why") or "explain" in low:
        return "why"
    if "neighbo" in low or "related to" in low:
        return "neighbors"
    if "timeline" in low or "when did" in low or "over time" in low or "history of" in low:
        return "timeline"
    if "contradict" in low or "conflict" in low:
        return "contradictions"
    if "communit" in low or "cluster" in low or "topic" in low:
        return "communities"
    if low.startswith("stats") or "how many" in low or low.startswith("count"):
        return "stats"
    return "reason"


def route(question: str, forced: str = "auto") -> RoutePlan:
    """Full routing decision: tool + strategy family + a short human-readable reason."""
    tool = classify_query(question, forced)
    strategy = STRATEGY.get(tool, "hybrid-multi-tool")
    if forced and forced != "auto":
        reason = f"caller forced tool={forced}"
    else:
        reason = {
            "gql": "looks like a declarative graph query",
            "path": "asks how two entities connect (multi-hop traversal)",
            "why": "asks for justification/claims about one entity",
            "neighbors": "asks what one entity relates to (one hop)",
            "timeline": "asks how something changed over time",
            "contradictions": "asks about conflicting assertions",
            "communities": "asks about clusters/topics",
            "stats": "asks for aggregate counts",
            "reason": "open question — Graph-of-Thoughts over hybrid retrieval",
        }.get(tool, "hybrid retrieval")
    return RoutePlan(tool=tool, strategy=strategy, reason=reason)
