"""L3 information-extraction intermediate representation.

Backend-agnostic: the rule extractor (default) and the GLiNER extractor (behind
``[ie]``) both produce these types, which the emitter turns into graph nodes/edges
with confidence tags and provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textgraph.core.layout import Span

# Canonical entity types (induced schema seeds these; users can extend).
ENTITY_TYPES = (
    "Organization",
    "Person",
    "Money",
    "Account",
    "Date",
    "Email",
)


@dataclass(frozen=True)
class Mention:
    """One surface occurrence of an entity, with its exact canonical-char span."""

    text: str
    etype: str
    span: Span
    norm: str
    via_coref: bool = False


@dataclass
class Entity:
    """A canonical entity (Phase-2 canonicalization = normalized surface + type).

    Full alias resolution ("Acme Corp" == "ACME") is Phase 3 (L5).
    """

    entity_id: str
    name: str
    etype: str
    mentions: list[Mention] = field(default_factory=list)


@dataclass(frozen=True)
class Relation:
    """A typed relation between two entities, asserted by a source span."""

    subject_id: str
    predicate: str  # canonical
    object_id: str
    surface: str  # surface predicate as evidence
    span: Span
    polarity: str = "pos"
    modality: str = "asserted"
    inferred: bool = False  # True if an endpoint was resolved via coref/alias
    amount: str = ""  # optional (e.g. Money for TRANSFERRED)


@dataclass
class IEResult:
    """Everything L2+L3 produced for one document."""

    entities: dict[str, Entity]
    relations: list[Relation]
    mentions: list[Mention]
    pronouns_total: int = 0
    pronouns_resolved: int = 0
