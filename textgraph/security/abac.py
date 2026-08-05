"""Attribute-Based Access Control conditions (Cedar-style), deterministic (Phase 9).

The gap analysis (§3.1) pairs ReBAC graph relations with a policy language such as Cedar
that evaluates ABAC attributes — "clearance level, IP origin, temporal window" — alongside
them. These are small, typed, immutable conditions doing exactly that: each ``allows`` the
principal against a *resource*'s own attributes (e.g. a document's classification). A
policy ANDs its rules, so every one must pass. No I/O, no clock — the caller supplies the
temporal instant via :class:`~textgraph.security.context.SecurityContext.as_of`, keeping
evaluation reproducible (G1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from textgraph.security.context import SecurityContext


@runtime_checkable
class AbacRule(Protocol):
    """A single attribute condition on (principal, resource)."""

    def allows(self, context: SecurityContext, resource: Mapping[str, str]) -> bool: ...


@dataclass(frozen=True)
class MinClearance:
    """Deny unless the principal's clearance meets the resource classification's floor.

    ``levels`` maps a classification label (the resource's ``classification`` attribute) to
    the minimum clearance required. Labels absent from the map require ``0`` (public).
    """

    levels: Mapping[str, int] = field(default_factory=dict)

    def allows(self, context: SecurityContext, resource: Mapping[str, str]) -> bool:
        required = self.levels.get(resource.get("classification", ""), 0)
        return context.clearance >= required


@dataclass(frozen=True)
class IpAllowlist:
    """Allow only requests whose origin IP matches one of the allowed prefixes.

    An empty ``prefixes`` allows all. A rule with prefixes denies a context with no ``ip``.
    Prefix (not full CIDR) matching keeps it dependency-free and deterministic.
    """

    prefixes: tuple[str, ...] = ()

    def allows(self, context: SecurityContext, resource: Mapping[str, str]) -> bool:
        if not self.prefixes:
            return True
        return any(context.ip.startswith(p) for p in self.prefixes if context.ip)


@dataclass(frozen=True)
class TimeWindow:
    """Allow only within an ISO-date window ``[not_before, not_after]`` (inclusive).

    Compares against the context's ``as_of`` instant (lexicographic ISO compare — no
    clock). A context with no ``as_of`` is denied whenever a bound is set: access under a
    temporal policy must state *when* it is being requested.
    """

    not_before: str | None = None
    not_after: str | None = None

    def allows(self, context: SecurityContext, resource: Mapping[str, str]) -> bool:
        if self.not_before is None and self.not_after is None:
            return True
        if context.as_of is None:
            return False
        if self.not_before is not None and context.as_of < self.not_before:
            return False
        return not (self.not_after is not None and context.as_of > self.not_after)
