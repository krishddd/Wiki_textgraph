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
    """A re-verifiable byte-range citation (G3)."""

    doc_id: str
    start: int  # raw byte offset, inclusive
    end: int  # raw byte offset, exclusive
    hash: str  # blake3 hex of raw[start:end]


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
