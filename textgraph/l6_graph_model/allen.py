"""Allen's interval algebra over bi-temporal claims (deterministic, dependency-free).

Every reified claim carries a validity window ``[t_valid, t_invalid)`` (L6). Allen's algebra is
the standard vocabulary for how two intervals relate in time — *before*, *meets*, *overlaps*,
*during*, *starts*, *finishes*, *equals*, and their inverses (13 relations in all). It turns
"these two facts were both true at some point" into a precise, queryable relationship: *did the
$1M transfer happen **during** the period Acme controlled Beta? Does the sanction **overlap** the
directorship?*

A claim's interval is ``[t_valid, t_invalid)``; an open end (``t_valid`` / ``t_invalid`` absent)
is treated as -inf / +inf. Endpoints are compared as strings, so ISO-8601 dates (``YYYY-MM-DD``)
order correctly — the same convention L6 invalidation already uses. Pure and deterministic:
iteration is over sorted claim ids, no clock, no dependency. Query-time only; ``graph.json`` is
untouched.
"""

from __future__ import annotations

from typing import Any

# The 13 Allen relations (7 base + 6 inverses), plus a friendly gloss for each.
RELATIONS: dict[str, str] = {
    "before": "ends before the other begins",
    "after": "begins after the other ends",
    "meets": "ends exactly when the other begins",
    "met_by": "begins exactly when the other ends",
    "overlaps": "starts first and overlaps into the other",
    "overlapped_by": "starts within the other and extends past it",
    "starts": "shares a start but ends first",
    "started_by": "shares a start but ends later",
    "during": "falls entirely within the other",
    "contains": "entirely contains the other",
    "finishes": "shares an end but starts later",
    "finished_by": "shares an end but starts earlier",
    "equals": "same interval",
}

# Endpoint ordering: (-1, "") is -inf, (1, "") is +inf, (0, value) is a finite date.
_Endpoint = tuple[int, str]


def _start(value: str | None) -> _Endpoint:
    return (0, value) if value else (-1, "")


def _end(value: str | None) -> _Endpoint:
    return (0, value) if value else (1, "")


def interval_of(props: dict[str, Any]) -> tuple[_Endpoint, _Endpoint]:
    """The ``[start, end)`` interval of a claim's properties (open ends → ±inf)."""
    tv = props.get("t_valid")
    ti = props.get("t_invalid")
    return _start(str(tv) if tv is not None else None), _end(str(ti) if ti is not None else None)


def allen_relation(a: tuple[_Endpoint, _Endpoint], b: tuple[_Endpoint, _Endpoint]) -> str:
    """The Allen relation of interval ``a`` to interval ``b`` (one of :data:`RELATIONS`)."""
    (a_s, a_e), (b_s, b_e) = a, b
    if a_e < b_s:
        return "before"
    if a_e == b_s:
        return "meets"
    if a_s > b_e:
        return "after"
    if a_s == b_e:
        return "met_by"
    # The intervals genuinely overlap in time; classify by their two endpoints.
    if a_s == b_s and a_e == b_e:
        return "equals"
    if a_s == b_s:
        return "starts" if a_e < b_e else "started_by"
    if a_e == b_e:
        return "finishes" if a_s > b_s else "finished_by"
    if a_s > b_s and a_e < b_e:
        return "during"
    if a_s < b_s and a_e > b_e:
        return "contains"
    if a_s < b_s:
        return "overlaps"
    return "overlapped_by"


def pairwise_relations(
    claims: list[dict[str, Any]], *, include_before_after: bool = False
) -> list[dict[str, Any]]:
    """Allen relation for every ordered pair of dated claims.

    ``claims`` are dicts with ``id``, ``label`` and ``t_valid``/``t_invalid``. Undated claims
    (no ``t_valid`` *and* no ``t_invalid``) are skipped — they have no interval. By default the
    trivial *before*/*after* pairs are omitted (usually the interesting relations are the
    temporal *overlaps*); pass ``include_before_after=True`` to keep them. Deterministic: pairs
    are emitted in sorted-id order.
    """
    dated = [c for c in claims if c.get("t_valid") is not None or c.get("t_invalid") is not None]
    dated.sort(key=lambda c: str(c.get("id", "")))
    out: list[dict[str, Any]] = []
    for i, ca in enumerate(dated):
        ia = interval_of(ca)
        for cb in dated[i + 1 :]:
            rel = allen_relation(ia, interval_of(cb))
            if not include_before_after and rel in ("before", "after"):
                continue
            out.append(
                {
                    "a": ca.get("label", ca.get("id")),
                    "b": cb.get("label", cb.get("id")),
                    "relation": rel,
                    "gloss": RELATIONS[rel],
                }
            )
    return out
