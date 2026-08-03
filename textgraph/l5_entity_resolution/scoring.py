"""Pairwise match scoring (L5, §8.2).

Deterministic feature blend: exact suffix-stripped match, Jaro-Winkler on the
normalized name, acronym↔name match, and the graph-native **relational** signal
(shared neighbours). Splink's calibrated Fellegi-Sunter probabilities are the
higher-quality alternative behind the ``[er]`` extra.
"""

from __future__ import annotations

from textgraph.l3_encoder_ie.canonicalize import suffix_family
from textgraph.l5_entity_resolution.model import ERecord
from textgraph.l5_entity_resolution.similarity import jaro_winkler, token_set_ratio

# Score at/above this is a match; the (LOW, MATCH) band is where an optional LLM
# adjudicator would sit (Phase 6). Below LOW is a non-match.
MATCH_THRESHOLD = 0.86
LOW_BAND = 0.6
# Same base name but conflicting suffix families ("Acme Bank" vs "Acme Corp") are
# usually different legal entities — score them below the match threshold.
_SUFFIX_CONFLICT = 0.7


def _shared_neighbor_boost(a: ERecord, b: ERecord) -> float:
    if not a.neighbors or not b.neighbors:
        return 0.0
    inter = a.neighbors & b.neighbors
    if not inter:
        return 0.0
    union = a.neighbors | b.neighbors
    return 0.1 * (len(inter) / len(union))  # up to +0.1 for fully shared context


def score_pair(a: ERecord, b: ERecord) -> float:
    """Return a match score in [0, 1] for two same-typed records."""
    if a.etype != b.etype:
        return 0.0
    if a.stripped and a.stripped == b.stripped:
        # Exact suffix-stripped equality is the strongest signal ("Acme Corp" /
        # "Acme Corporation" / "ACME" all strip to "acme") — UNLESS the two carry
        # conflicting explicit suffix families (Bank vs Corp), which usually marks
        # distinct legal entities.
        fa, fb = suffix_family(a.name), suffix_family(b.name)
        base = _SUFFIX_CONFLICT if (fa and fb and fa != fb) else 0.95
    else:
        # Similarity on the *stripped* base names, so a shared suffix ("Corp") can't
        # inflate the score ("Acme Corp" vs "Apex Corp" must not match).
        name_sim = jaro_winkler(a.stripped, b.stripped)
        token_sim = token_set_ratio(a.stripped, b.stripped)
        acr = (
            0.9
            if (a.acronym and a.acronym == b.stripped.replace(" ", ""))
            or (b.acronym and b.acronym == a.stripped.replace(" ", ""))
            else 0.0
        )
        base = max(name_sim, token_sim, acr)
    return min(1.0, base + _shared_neighbor_boost(a, b))
