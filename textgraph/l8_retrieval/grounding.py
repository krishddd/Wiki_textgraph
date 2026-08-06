"""Answer-grounding confidence + abstention (Sprint 3.3).

An honest system says "I don't know" rather than surfacing a confident-looking guess with
no support. This module scores how well an answer is *grounded* in the graph — from the
amount of re-verifiable citation evidence behind it — and decides whether to **abstain**.

Deterministic and pure (a small monotone function of the evidence count), so the decision is
reproducible (G1) and explainable (G6): the confidence and the abstain flag can be shown to
the user. Abstention applies only to *factual* answers (a claim that needs support); an empty
aggregate ("0 contradictions", "3 communities") is a valid answer, not an abstention.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tools whose answer is a factual claim and therefore must be grounded to be trusted.
_FACTUAL = frozenset({"search", "why", "path", "neighbors", "timeline", "reason"})
# Below this confidence a factual answer is not worth asserting.
_ABSTAIN_BELOW = 0.25

ABSTENTION_TEXT = "Insufficient evidence in the graph to answer that confidently."


@dataclass(frozen=True)
class Grounding:
    """How well an answer is supported, and whether to abstain."""

    confidence: float
    abstain: bool


def assess(tool: str, *, evidence_count: int, has_focus: bool = True) -> Grounding:
    """Score grounding from the citation evidence behind an answer and decide abstention.

    Non-factual tools (stats / communities / contradictions / gql) are always confident — an
    empty result there is a real answer. Factual tools need citations: zero evidence abstains;
    more distinct cited spans raise confidence (saturating), lightly penalised if the answer
    couldn't even anchor on a focus entity.
    """
    if tool not in _FACTUAL:
        return Grounding(confidence=1.0, abstain=False)
    if evidence_count <= 0:
        return Grounding(confidence=0.0, abstain=True)
    # 1 span -> 0.6, 2 -> 0.75, 3 -> 0.9, 4+ -> 1.0; small penalty with no focus anchor.
    conf = min(1.0, 0.45 + 0.15 * min(evidence_count, 4))
    if not has_focus:
        conf *= 0.8
    return Grounding(confidence=round(conf, 3), abstain=conf < _ABSTAIN_BELOW)
