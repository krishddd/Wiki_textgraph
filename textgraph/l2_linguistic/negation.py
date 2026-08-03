"""Negation & modality detection (L2, NegEx-style rule pack).

Prevents the classic failure of asserting ``X TRANSFERRED Y`` from "X did not
transfer to Y". Relations get ``polarity`` (pos/neg) and ``modality``
(asserted/hedged) attributes — never silently dropped (§5, §16).
"""

from __future__ import annotations

import re

_NEGATIONS = re.compile(
    r"\b(?:no|not|never|without|denies?|denied|failed to|did not|does not|didn't|"
    r"doesn't|cannot|can't|couldn't|won't|wouldn't|neither|nor|absent|lack(?:s|ed)?)\b",
    re.IGNORECASE,
)
_HEDGES = re.compile(
    r"\b(?:may|might|could|possibly|allegedly|apparently|reportedly|suspected|"
    r"appears?|seems?|likely|probably|potential(?:ly)?|believed|claims?|claimed)\b",
    re.IGNORECASE,
)


def polarity(text: str) -> str:
    """Return 'neg' if the clause is negated, else 'pos'."""
    return "neg" if _NEGATIONS.search(text) else "pos"


def modality(text: str) -> str:
    """Return 'hedged' if the clause is hedged/uncertain, else 'asserted'."""
    return "hedged" if _HEDGES.search(text) else "asserted"
