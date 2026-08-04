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
    """A re-verifiable byte-range pointer into a source document (G3)."""

    doc_id: str
    start: int
    end: int
    hash: str

    def ref(self) -> str:
        return f"[{self.doc_id}:{self.start}-{self.end}]"

    def to_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "start": self.start, "end": self.end, "hash": self.hash}


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
