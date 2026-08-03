"""Predicate & entity canonicalization (L3, §6.3).

Surface predicates are mapped to a small canonical set (keeping the surface form as
evidence, never discarded). Entity ids are content-addressed on ``type + normalized
name`` so the same entity merges across documents; alias-level resolution is Phase 3.
"""

from __future__ import annotations

import re

# surface verb/phrase -> canonical predicate. Ordered longest-first at match time.
PREDICATE_MAP: dict[str, str] = {
    "wired": "TRANSFERRED",
    "wire": "TRANSFERRED",
    "transferred": "TRANSFERRED",
    "transfer": "TRANSFERRED",
    "sent": "TRANSFERRED",
    "send": "TRANSFERRED",
    "paid": "TRANSFERRED",
    "pay": "TRANSFERRED",
    "remitted": "TRANSFERRED",
    "remit": "TRANSFERRED",
    "moved": "TRANSFERRED",
    "routed": "TRANSFERRED",
    "deposited": "TRANSFERRED",
    "owns": "CONTROLS",
    "controls": "CONTROLS",
    "holds": "CONTROLS",
    "controlled by": "CONTROLLED_BY",
    "owned by": "CONTROLLED_BY",
    "director of": "DIRECTOR_OF",
    "nominee director of": "DIRECTOR_OF",
    "ceo of": "DIRECTOR_OF",
    "officer of": "DIRECTOR_OF",
    "beneficial owner of": "BENEFICIAL_OWNER_OF",
    "associated with": "ASSOCIATED_WITH",
    "linked to": "ASSOCIATED_WITH",
    "connected to": "ASSOCIATED_WITH",
}

_WS = re.compile(r"\s+")
_ORG_SUFFIX = re.compile(
    r"\b(?:corp(?:oration)?|ltd|limited|llc|inc(?:orporated)?|plc|gmbh|s\.?a\.?|"
    r"bank|group|holdings?|trust|fund|partners|co)\b\.?",
    re.IGNORECASE,
)


def canonical_predicate(surface: str) -> str:
    key = _WS.sub(" ", surface.strip().lower())
    return PREDICATE_MAP.get(key, key.upper().replace(" ", "_"))


def normalize_name(name: str) -> str:
    """Lowercase, collapse whitespace, drop trailing punctuation for entity keys."""
    return _WS.sub(" ", name.strip().strip(".,;:'\"")).lower()


def entity_id(etype: str, name: str) -> str:
    return f"entity:{etype}:{normalize_name(name)}"


def strip_org_suffix(name: str) -> str:
    return _ORG_SUFFIX.sub("", name).strip()


# Org suffix -> family. Corp/Corporation are the same family; Bank/Corp are not.
_SUFFIX_FAMILY = {
    "corp": "corp",
    "corporation": "corp",
    "ltd": "ltd",
    "limited": "ltd",
    "inc": "inc",
    "incorporated": "inc",
    "llc": "llc",
    "plc": "plc",
    "gmbh": "gmbh",
    "sa": "sa",
    "bank": "bank",
    "group": "group",
    "holding": "holdings",
    "holdings": "holdings",
    "trust": "trust",
    "fund": "fund",
    "partners": "partners",
    "co": "co",
}


def suffix_family(name: str) -> str:
    """Return the normalized org suffix family of ``name`` ('' if none).

    Used by entity resolution to keep same-base but differently-incorporated
    entities apart ("Acme Bank" vs "Acme Corp"), which are usually distinct.
    """
    toks = normalize_name(name).replace(".", "").split()
    if not toks:
        return ""
    return _SUFFIX_FAMILY.get(toks[-1], "")
