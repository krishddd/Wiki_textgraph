"""L5 entity-resolution data model.

Resolution is **non-destructive** (§8.3): original entity nodes are kept, and a new
canonical node is linked to each member via a ``SAME_AS`` edge. Everything here is
plain data so the resolver can be tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textgraph.store.base import SourceSpan


@dataclass(frozen=True)
class ERecord:
    """One entity to be resolved, plus the signals used to match it."""

    entity_id: str
    name: str
    etype: str
    norm: str  # normalized name
    stripped: str  # suffix-stripped normalized name (Acme Corp / Corporation -> acme)
    acronym: str  # initials of a multi-token name
    mention_spans: tuple[SourceSpan, ...]
    neighbors: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SameAs:
    """A non-destructive link: ``member_id`` is the same real-world entity as
    ``canonical_id`` (tagged INFERRED downstream)."""

    member_id: str
    canonical_id: str
    score: float
    source: SourceSpan


@dataclass
class Cluster:
    canonical_id: str
    canonical_name: str
    etype: str
    members: list[str] = field(default_factory=list)


@dataclass
class ERResult:
    clusters: list[Cluster]
    same_as: list[SameAs]
    candidate_pairs: int = 0
    cross_product: int = 0
