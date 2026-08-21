"""GraphStore interface (stub for Phase 0).

Defines the minimal typed surface that L6 (assembly), L7 (analytics) and L8
(retrieval) will call. Concrete backends (NetworkX in-memory, DuckDB/Parquet on
disk, and later a GQL-native engine) implement this. Confidence tags and byte-span
provenance are first-class on every edge (G3, G4).

Phase 0 ships the interface only; methods raise ``NotImplementedError``. The
in-memory and DuckDB backends land in Phase 4 alongside L6.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ConfidenceTag(StrEnum):
    """Four-tier trust taxonomy stamped on every edge (G4)."""

    STRUCTURAL = "STRUCTURAL"
    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    GENERATED = "GENERATED"


@dataclass(frozen=True)
class SourceSpan:
    """A re-verifiable byte-range citation (G3).

    ``page`` is an optional 1-based page number for paged sources (PDFs); ``0`` means
    unknown/unpaged. ``bbox`` is an optional ``(x0, y0, x1, y1)`` bounding box in PDF points
    (page coordinate space, origin bottom-left) locating the cited text on its page. Both are
    strictly additive layout provenance — the byte range is still the source of truth and
    re-verification never consults them — so text corpora and pre-layout graphs stay
    byte-identical (the fields are omitted from ``graph.json`` when absent).
    """

    doc_id: str
    start: int  # raw byte offset, inclusive
    end: int  # raw byte offset, exclusive
    hash: str  # blake3 hex of raw[start:end]
    page: int = 0  # 1-based page for paged sources; 0 = unknown/unpaged
    bbox: tuple[float, float, float, float] | None = None  # (x0,y0,x1,y1) in PDF points


def span_to_dict(s: SourceSpan) -> dict[str, Any]:
    """Serialize a SourceSpan; ``page``/``bbox`` are emitted only when known, so text-only
    corpora and pre-layout graphs stay byte-identical (G1) — the fields are purely additive."""
    d: dict[str, Any] = {"doc_id": s.doc_id, "start": s.start, "end": s.end, "hash": s.hash}
    if s.page:
        d["page"] = s.page
    if s.bbox is not None:
        d["bbox"] = list(s.bbox)
    return d


def span_from_dict(s: dict[str, Any]) -> SourceSpan:
    """Reconstruct a SourceSpan, tolerating pre-5.2 spans without page/bbox (default absent)."""
    bbox = s.get("bbox")
    return SourceSpan(
        doc_id=s["doc_id"],
        start=s["start"],
        end=s["end"],
        hash=s["hash"],
        page=int(s.get("page", 0)),
        bbox=tuple(bbox) if bbox is not None else None,
    )


@dataclass(frozen=True)
class Node:
    node_id: str
    labels: tuple[str, ...] = ()
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    edge_id: str
    subject: str
    predicate: str
    object: str
    tag: ConfidenceTag
    confidence: float
    evidence_count: int = 0
    source_spans: tuple[SourceSpan, ...] = ()
    properties: dict[str, Any] = field(default_factory=dict)


class GraphStore(ABC):
    """Backend-agnostic property-graph store.

    Implementations must preserve deterministic iteration order (sorted by stable
    key) so artifacts built from a store are byte-stable (G1).
    """

    @abstractmethod
    def add_node(self, node: Node) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_edge(self, edge: Edge) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        raise NotImplementedError

    @abstractmethod
    def neighbors(self, node_id: str) -> list[Edge]:
        raise NotImplementedError

    @abstractmethod
    def nodes(self) -> list[Node]:
        """All nodes in deterministic (sorted-by-id) order."""
        raise NotImplementedError

    @abstractmethod
    def edges(self) -> list[Edge]:
        """All edges in deterministic (sorted-by-stable-key) order."""
        raise NotImplementedError
