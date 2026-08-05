"""Late-interaction MaxSim scoring (Phase 8, vision-native retrieval).

The heart of ColPali-style visual document retrieval: a query and a page are each a
**multi-vector** — a list of per-token / per-patch vectors — and their relevance is the
MaxSim operator ``score = sum_i max_j (q_i . p_j)`` (§2.1 of the gap analysis): every
query token is matched to its single best-aligning page patch, and the alignments are
summed. It works identically whether the vectors come from the deterministic default
embedder or a real ColPali/ColQwen model behind the ``[vision]`` extra — this module
never sees an image, only vectors — so the algorithm is pure-Python, deterministic
(G1), and fully unit-testable in CI without a GPU.
"""

from __future__ import annotations

import math

# A multi-vector: one vector per query token or page patch.
Vector = tuple[float, ...]
MultiVector = tuple[Vector, ...]


def dot(a: Vector, b: Vector) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))


def normalize(v: Vector) -> Vector:
    norm = math.sqrt(math.fsum(x * x for x in v))
    if norm == 0.0:
        return v
    return tuple(x / norm for x in v)


def maxsim(query: MultiVector, page: MultiVector) -> float:
    """MaxSim late-interaction score between a query and a page multi-vector.

    ``sum over query vectors of (max over page vectors of their dot product)``. Assumes
    unit-normalised vectors (so each dot is a cosine in ``[-1, 1]``); returns 0 for an
    empty query or page. Deterministic given deterministic inputs.
    """
    if not query or not page:
        return 0.0
    total = 0.0
    for q in query:
        total += max(dot(q, p) for p in page)
    return total
