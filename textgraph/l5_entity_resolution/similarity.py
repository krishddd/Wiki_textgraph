"""Deterministic string similarity for entity resolution (L5).

Pure-Python Jaro-Winkler and token-set ratio — no external deps, no randomness, so
scoring is byte-reproducible (G1). Splink's probabilistic Fellegi-Sunter scoring is
the higher-quality option behind the ``[er]`` extra.
"""

from __future__ import annotations


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    match_dist = max(len(a), len(b)) // 2 - 1
    match_dist = max(match_dist, 0)
    a_match = [False] * len(a)
    b_match = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        lo = max(0, i - match_dist)
        hi = min(i + match_dist + 1, len(b))
        for j in range(lo, hi):
            if not b_match[j] and b[j] == ca:
                a_match[i] = b_match[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    # Transpositions.
    t = 0.0
    k = 0
    for i in range(len(a)):
        if a_match[i]:
            while not b_match[k]:
                k += 1
            if a[i] != b[k]:
                t += 1
            k += 1
    t /= 2
    m = float(matches)
    return (m / len(a) + m / len(b) + (m - t) / m) / 3.0


def jaro_winkler(a: str, b: str, *, prefix_weight: float = 0.1) -> float:
    """Jaro-Winkler similarity in [0, 1] with the standard common-prefix boost."""
    j = jaro(a, b)
    prefix = 0
    for ca, cb in zip(a, b, strict=False):
        if ca == cb:
            prefix += 1
        else:
            break
        if prefix == 4:
            break
    return j + prefix * prefix_weight * (1 - j)


def token_set_ratio(a: str, b: str) -> float:
    """Jaccard overlap of the whitespace token sets of ``a`` and ``b``."""
    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def acronym(name: str) -> str:
    """Initials of a multi-token name, e.g. 'International Business Machines' -> 'ibm'."""
    toks = [t for t in name.split() if t]
    if len(toks) < 2:
        return ""
    return "".join(t[0] for t in toks).lower()
