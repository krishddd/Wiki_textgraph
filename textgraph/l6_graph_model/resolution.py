"""Deterministic contradiction-resolution *hints* (read-only, non-destructive).

Contradiction *detection* is done (`CONTRADICTS` edges); this closes the analyst loop by
recommending, for each contested pair, which claim most likely supersedes the other — and
*why* — without ever mutating the graph. The analyst stays in control: a hint is a suggestion
plus a rationale, and the actual invalidation is a separate, explicit step
(`build --resolve-conflicts <strategy>`), which writes a cited `SUPERSEDES` edge rather than
deleting anything.

The recommendation is a fixed, auditable rule ladder (no model):

1. **Recency** — a claim with a later ``t_valid`` supersedes an earlier one (a dated correction
   is the canonical case: "on 2026-06-01, X did *not* transfer …" overrides the May assertion).
2. **Confidence** — if neither is dated (or the dates tie), the higher-confidence claim wins.
3. **Otherwise** — no confident recommendation; flag for manual review.

Pure and deterministic: same inputs, same hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _Claim(Protocol):
    claim_id: str
    subject: str
    predicate: str
    object: str
    polarity: str
    confidence: float
    t_valid: str | None
    t_invalid: str | None


@dataclass
class ResolutionHint:
    """A recommendation for one contradicted pair (which side, and why)."""

    recommend: str | None  # "a", "b", or None (manual review)
    basis: str  # "recency" | "confidence" | "none"
    reason: str  # human-readable rationale

    def to_dict(self) -> dict[str, Any]:
        return {"recommend": self.recommend, "basis": self.basis, "reason": self.reason}


def _short(c: _Claim) -> str:
    neg = " (negated)" if getattr(c, "polarity", "pos") == "neg" else ""
    return f"{c.subject} {c.predicate} {c.object}{neg}"


def resolution_hint(a: _Claim, b: _Claim) -> ResolutionHint:
    """Recommend which of two contradicting claims most likely supersedes the other."""
    av, bv = a.t_valid, b.t_valid
    # 1) Recency: a later validity date wins (dated correction supersedes).
    if av is not None and bv is not None and av != bv:
        if bv > av:
            return ResolutionHint(
                "b", "recency", f"'{_short(b)}' is dated {bv}, later than '{_short(a)}' ({av})."
            )
        return ResolutionHint(
            "a", "recency", f"'{_short(a)}' is dated {av}, later than '{_short(b)}' ({bv})."
        )
    # A one-sided date is still a signal: the dated claim is the more specific record.
    if (av is None) != (bv is None):
        if bv is not None:
            return ResolutionHint(
                "b", "recency", f"'{_short(b)}' carries a date ({bv}); '{_short(a)}' does not."
            )
        return ResolutionHint(
            "a", "recency", f"'{_short(a)}' carries a date ({av}); '{_short(b)}' does not."
        )
    # 2) Confidence: the better-supported claim wins (needs a meaningful margin).
    if abs(a.confidence - b.confidence) >= 0.05:
        if a.confidence > b.confidence:
            return ResolutionHint(
                "a",
                "confidence",
                f"'{_short(a)}' has higher confidence ({a.confidence:.2f} vs {b.confidence:.2f}).",
            )
        return ResolutionHint(
            "b",
            "confidence",
            f"'{_short(b)}' has higher confidence ({b.confidence:.2f} vs {a.confidence:.2f}).",
        )
    # 3) No basis to choose — the analyst must decide.
    return ResolutionHint(
        None, "none", "Neither claim is dated nor clearly better supported — review manually."
    )
