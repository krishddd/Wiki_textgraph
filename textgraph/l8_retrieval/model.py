"""Typed, bounded, cited result objects for the L8 query surface (G6, G7).

Every tool returns one of these dataclasses rather than raw graph rows or Cypher.
Each object is JSON-serialisable (``to_dict``) and self-describing, and every factual
row carries a :class:`Citation` — a ``[doc:start-end]`` byte pointer an agent can
re-verify (G3). A shared :func:`estimate_tokens` / :func:`budget_items` keeps every
context pack under an explicit token ceiling (G7): retrieval that cannot bound its
own cost is not agent-legible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~4 chars/token). No tokenizer dep."""
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class Citation:
    """A re-verifiable byte-range pointer into a source document (G3).

    ``page`` is optional 1-based layout provenance (0 = unknown); when present it prefixes
    the human-facing ``ref()`` as ``p.N`` and is carried in ``to_dict()``, but the byte
    range remains the identity — page never affects re-verification.
    """

    doc_id: str
    start: int
    end: int
    hash: str
    page: int = 0

    def ref(self) -> str:
        loc = f"p.{self.page} " if self.page else ""
        return f"[{loc}{self.doc_id}:{self.start}-{self.end}]"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "doc_id": self.doc_id,
            "start": self.start,
            "end": self.end,
            "hash": self.hash,
        }
        if self.page:
            d["page"] = self.page
        return d


def budget_items(items: list[Any], texts: list[str], max_tokens: int) -> tuple[list[Any], bool]:
    """Truncate a ranked list so its cumulative text stays within ``max_tokens``.

    Returns ``(kept, truncated)``. Always keeps at least the first item so a result
    is never empty purely from budgeting.
    """
    kept: list[Any] = []
    used = 0
    for item, text in zip(items, texts, strict=False):
        cost = estimate_tokens(text)
        if kept and used + cost > max_tokens:
            return kept, True
        kept.append(item)
        used += cost
    return kept, False


@dataclass
class SearchHit:
    node_id: str
    kind: str  # "chunk" | "entity"
    name: str
    score: float
    snippet: str = ""
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "score": round(self.score, 6),
            "snippet": self.snippet,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class SearchResult:
    query: str
    routing: str  # "local" | "global"
    hits: list[SearchHit] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "search",
            "query": self.query,
            "routing": self.routing,
            "hits": [h.to_dict() for h in self.hits],
            "truncated": self.truncated,
        }


@dataclass
class NeighborEdge:
    predicate: str
    direction: str  # "out" | "in"
    other_id: str
    other_name: str
    tag: str
    confidence: float
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "predicate": self.predicate,
            "direction": self.direction,
            "other_id": self.other_id,
            "other_name": self.other_name,
            "tag": self.tag,
            "confidence": round(self.confidence, 6),
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class NeighborsResult:
    node_id: str
    name: str
    neighbors: list[NeighborEdge] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "neighbors",
            "node_id": self.node_id,
            "name": self.name,
            "neighbors": [n.to_dict() for n in self.neighbors],
            "truncated": self.truncated,
        }


@dataclass
class PathStep:
    subject: str
    predicate: str
    object: str
    tag: str
    confidence: float
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "tag": self.tag,
            "confidence": round(self.confidence, 6),
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class GraphPath:
    nodes: list[str]
    steps: list[PathStep]
    likelihood: float  # product of edge confidences

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "steps": [s.to_dict() for s in self.steps],
            "likelihood": round(self.likelihood, 6),
        }


@dataclass
class PathResult:
    source: str
    target: str
    paths: list[GraphPath] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "path",
            "source": self.source,
            "target": self.target,
            "paths": [p.to_dict() for p in self.paths],
        }


@dataclass
class ClaimView:
    claim_id: str
    subject: str
    predicate: str
    object: str
    polarity: str
    modality: str
    confidence: float
    t_valid: str | None
    tag: str
    t_invalid: str | None = None
    citations: list[Citation] = field(default_factory=list)

    @property
    def status(self) -> str:
        """``superseded`` once a later claim closed this one's window, else ``current``."""
        return "superseded" if self.t_invalid else "current"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "polarity": self.polarity,
            "modality": self.modality,
            "confidence": round(self.confidence, 6),
            "t_valid": self.t_valid,
            "t_invalid": self.t_invalid,
            "status": self.status,
            "tag": self.tag,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class WhyResult:
    node_id: str
    name: str
    claims: list[ClaimView] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "why",
            "node_id": self.node_id,
            "name": self.name,
            "claims": [c.to_dict() for c in self.claims],
            "rationale": self.rationale,
            "truncated": self.truncated,
        }


@dataclass
class TimelineResult:
    node_id: str
    name: str
    events: list[ClaimView] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "timeline",
            "node_id": self.node_id,
            "name": self.name,
            "events": [c.to_dict() for c in self.events],
        }


@dataclass
class ContradictionPair:
    claim_a: ClaimView
    claim_b: ClaimView

    def to_dict(self) -> dict[str, Any]:
        return {"claim_a": self.claim_a.to_dict(), "claim_b": self.claim_b.to_dict()}


@dataclass
class ContradictionsResult:
    pairs: list[ContradictionPair] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": "contradictions", "pairs": [p.to_dict() for p in self.pairs]}


@dataclass
class ConflictView:
    """One single-truth conflict: competing claims about the same subject+predicate."""

    conflict_id: str
    subject: str
    predicate: str
    severity: str
    objects: list[str]
    claims: list[ClaimView] = field(default_factory=list)
    resolution_strategy: str = ""  # "" until an opt-in strategy resolved it
    resolved_object: str | None = None  # the winning object's name (None if unresolved)
    resolution_note: str = ""  # why it stayed unresolved, if applicable

    @property
    def resolved(self) -> bool:
        return self.resolved_object is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "subject": self.subject,
            "predicate": self.predicate,
            "severity": self.severity,
            "objects": self.objects,
            "claims": [c.to_dict() for c in self.claims],
            "resolution_strategy": self.resolution_strategy,
            "resolved_object": self.resolved_object,
            "resolved": self.resolved,
            "resolution_note": self.resolution_note,
        }


@dataclass
class ConflictsResult:
    conflicts: list[ConflictView] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": "conflicts", "conflicts": [c.to_dict() for c in self.conflicts]}


@dataclass
class DecisionRef:
    """A Decision node, cited to the byte span it was derived from."""

    decision_id: str
    name: str
    category: str
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "name": self.name,
            "category": self.category,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class ChainHop:
    """One causal edge in a decision chain: ``from`` --relation--> ``to`` (cause -> effect)."""

    relation: str  # CAUSED | INFLUENCED | PRECEDENT_FOR
    from_id: str
    from_name: str
    to_id: str
    to_name: str
    depth: int
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "from_id": self.from_id,
            "from_name": self.from_name,
            "to_id": self.to_id,
            "to_name": self.to_name,
            "depth": self.depth,
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class DecisionChainResult:
    """The causal lineage of a decision: what led to it (ancestors) and what it led to."""

    found: bool
    decision: DecisionRef | None = None
    ancestors: list[ChainHop] = field(default_factory=list)  # causes (traversed backward)
    descendants: list[ChainHop] = field(default_factory=list)  # effects (traversed forward)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "trace_decision_chain",
            "found": self.found,
            "decision": self.decision.to_dict() if self.decision else None,
            "ancestors": [h.to_dict() for h in self.ancestors],
            "descendants": [h.to_dict() for h in self.descendants],
            "truncated": self.truncated,
        }


@dataclass
class DecisionHit:
    decision_id: str
    name: str
    category: str
    score: float
    citations: list[Citation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "name": self.name,
            "category": self.category,
            "score": round(self.score, 6),
            "citations": [c.to_dict() for c in self.citations],
        }


@dataclass
class SimilarDecisionsResult:
    query: str
    hits: list[DecisionHit] = field(default_factory=list)
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "find_similar_decisions",
            "query": self.query,
            "hits": [h.to_dict() for h in self.hits],
            "truncated": self.truncated,
        }


@dataclass
class CommunityView:
    community_id: int
    label: str
    size: int
    members: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "community_id": self.community_id,
            "label": self.label,
            "size": self.size,
            "members": self.members,
        }


@dataclass
class CommunitiesResult:
    communities: list[CommunityView] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "communities",
            "communities": [c.to_dict() for c in self.communities],
        }


@dataclass
class StatsResult:
    counts: dict[str, int] = field(default_factory=dict)
    top_entities: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": "stats", "counts": self.counts, "top_entities": self.top_entities}


def as_dict(obj: Any) -> dict[str, Any]:
    """Serialise any result object (falls back to ``asdict`` for plain dataclasses)."""
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        result: dict[str, Any] = to_dict()
        return result
    return asdict(obj)
