"""The authenticated security context carried by every guarded tool call (Phase 9).

A :class:`SecurityContext` is the *token* the gap analysis (§3.2) says each agent tool
invocation (``search``, ``neighbors``, ``path`` …) must present before any subgraph is
materialised. It names the principal, the group memberships that drive ReBAC lookups,
and the ABAC attributes (clearance, IP origin, temporal window) evaluated against a
resource's own attributes. It is immutable and hashable, so a build that threads the
*same* context is deterministic (G1); the object never appears in ``graph.json`` — access
control is a query-time concern, so the artifact is byte-identical whether or not a policy
is attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SecurityContext:
    """Who is asking, plus the attributes a policy evaluates against.

    ``principal`` is the subject id (``alice`` -> the ReBAC subject ``user:alice``).
    ``groups`` are direct group ids the principal belongs to (ReBAC subjects
    ``group:<g>``). ``clearance`` is the ABAC clearance level (higher dominates), ``ip``
    the request origin, and ``as_of`` an ISO date bounding a temporal window — all
    optional so a bare ``SecurityContext("alice")`` is valid.
    """

    principal: str
    groups: frozenset[str] = field(default_factory=frozenset)
    clearance: int = 0
    ip: str = ""
    as_of: str | None = None

    @property
    def subject(self) -> str:
        """The ReBAC subject reference for this principal (``user:<principal>``)."""
        return f"user:{self.principal}"

    def subjects(self) -> frozenset[str]:
        """Every ReBAC subject this context can act as: the user and its groups."""
        return frozenset({self.subject, *(f"group:{g}" for g in self.groups)})
