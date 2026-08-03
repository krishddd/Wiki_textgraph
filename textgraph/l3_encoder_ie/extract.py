"""L2+L3 orchestration for one document (default rule backend).

Segments sentences (L2), detects entity mentions (L3), resolves pronouns/definite
NPs to the nearest compatible entity (coref-lite, L2), and extracts typed relations
per sentence. Relations whose subject/object were filled via coref are marked
``inferred`` (tag INFERRED downstream); the rest are EXTRACTED. Deterministic (G1).
"""

from __future__ import annotations

import re

from textgraph.core.layout import Block, BlockKind, Span
from textgraph.l2_linguistic import modality, polarity, segment
from textgraph.l3_encoder_ie.canonicalize import (
    canonical_predicate,
    entity_id,
    normalize_name,
    strip_org_suffix,
)
from textgraph.l3_encoder_ie.model import Entity, IEResult, Mention, Relation
from textgraph.l3_encoder_ie.rules import extract_entities

# All-caps token (ACME, IBM). Marker/RFC words that must never be read as an org.
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")
_ACRONYM_STOP = frozenset(
    {
        "MUST",
        "SHALL",
        "SHOULD",
        "MAY",
        "WHY",
        "TODO",
        "ADR",
        "RFC",
        "SAR",
        "AML",
        "KYC",
        "INFO",
        "WARN",
        "ERROR",
        "DEBUG",
        "NOTE",
        "OK",
        "ID",
        "URL",
    }
)

# Predicate surfaces, longest first so "nominee director of" beats "director of".
_SURFACES = sorted(
    [
        "nominee director of",
        "beneficial owner of",
        "controlled by",
        "owned by",
        "director of",
        "officer of",
        "ceo of",
        "associated with",
        "linked to",
        "connected to",
        "wired",
        "wire",
        "transferred",
        "transfer",
        "remitted",
        "remit",
        "deposited",
        "routed",
        "sent",
        "send",
        "paid",
        "pay",
        "moved",
        "owns",
        "controls",
        "holds",
    ],
    key=len,
    reverse=True,
)
_PRED_RE = re.compile("|".join(rf"\b{re.escape(s)}\b" for s in _SURFACES), re.IGNORECASE)
_FROM_TO = re.compile(r"\bfrom\b(?P<mid>.+?)\bto\b", re.IGNORECASE | re.DOTALL)
_ORG_PRONOUN = re.compile(
    r"\b(it|they|them|the company|the firm|the bank|the entity|the corporation)\b",
    re.IGNORECASE,
)
_PERSON_PRONOUN = re.compile(
    r"\b(he|she|him|her|the director|the officer|the individual|the suspect)\b",
    re.IGNORECASE,
)
_TRANSFER_NOUN = re.compile(r"\b(?:transfers?|wires?|payments?|remittances?)\b", re.IGNORECASE)


def _mentions_in(mentions: list[Mention], span: Span) -> list[Mention]:
    return [m for m in mentions if m.span.start >= span.start and m.span.end <= span.end]


def _nearest_before(cands: list[Mention], pos: int) -> Mention | None:
    best = None
    for m in cands:
        if m.span.end <= pos and (best is None or m.span.end > best.span.end):
            best = m
    return best


def _nearest_after(cands: list[Mention], pos: int) -> Mention | None:
    best = None
    for m in cands:
        if m.span.start >= pos and (best is None or m.span.start < best.span.start):
            best = m
    return best


class _Coref:
    """Resolve org/person pronouns to the nearest preceding compatible mention."""

    def __init__(self, mentions: list[Mention]) -> None:
        self._orgs = [m for m in mentions if m.etype == "Organization"]
        self._persons = [m for m in mentions if m.etype == "Person"]
        self.total = 0
        self.resolved = 0

    def resolve(self, kind: str, pos: int) -> Mention | None:
        """Pure lookup used for relation slot-filling — never touches counters.

        The coverage metric is computed once by :meth:`count_coverage`; counting here
        too would double-count pronouns that also fill a relation slot.
        """
        pool = self._orgs if kind == "org" else self._persons
        return _nearest_before(pool, pos)

    def count_coverage(self, text: str, spans: list[Span]) -> None:
        """Count resolvable pronouns across the prose blocks (the coverage metric)."""
        for bs in spans:
            sub = text[bs.start : bs.end]
            for pat, kind in ((_ORG_PRONOUN, "org"), (_PERSON_PRONOUN, "person")):
                for m in pat.finditer(sub):
                    pool = self._orgs if kind == "org" else self._persons
                    self.total += 1
                    if _nearest_before(pool, bs.start + m.start()) is not None:
                        self.resolved += 1


def _resolve_slot(
    entity_slot: Mention | None,
    sub_text: str,
    abs_offset: int,
    side_pos: int,
    coref: _Coref,
    entities: dict[str, Entity],
    before: bool,
) -> tuple[str | None, bool]:
    """Return (entity_id, inferred). Falls back to coref if no entity in slot."""
    if entity_slot is not None:
        return entity_id(entity_slot.etype, entity_slot.text), False
    # Look for a pronoun on the relevant side within the sentence.
    for pat, kind in ((_ORG_PRONOUN, "org"), (_PERSON_PRONOUN, "person")):
        for pm in pat.finditer(sub_text):
            p_abs = abs_offset + pm.start()
            if (before and p_abs < side_pos) or (not before and p_abs > side_pos):
                ant = coref.resolve(kind, p_abs)
                if ant is not None:
                    eid = entity_id(ant.etype, ant.text)
                    if eid in entities:
                        return eid, True
    return None, False


# Prose blocks that IE runs over. Entities/sentences are confined to a block so a
# heading word never merges with the paragraph below it; coref still runs doc-wide.
_PROSE_BLOCKS = {
    BlockKind.HEADING,
    BlockKind.PARAGRAPH,
    BlockKind.LIST_ITEM,
    BlockKind.QUOTE,
    BlockKind.TRANSCRIPT_TURN,
}


def _prose_units(text: str, blocks: list[Block] | None) -> list[tuple[Span, BlockKind]]:
    if blocks is None:
        return [(Span(0, len(text)), BlockKind.PARAGRAPH)]
    return [
        (b.span, b.kind)
        for top in blocks
        for b in top.walk()
        if b.kind in _PROSE_BLOCKS and b.span.end > b.span.start
    ]


def extract_document(text: str, blocks: list[Block] | None = None) -> IEResult:
    units = _prose_units(text, blocks)
    block_spans = [span for span, _ in units]

    # Detect mentions within each block, then shift spans to absolute canonical coords.
    mentions: list[Mention] = []
    for bs, kind in units:
        for m in extract_entities(
            text[bs.start : bs.end], allow_person_bigram=kind is not BlockKind.HEADING
        ):
            mentions.append(
                Mention(
                    text=m.text,
                    etype=m.etype,
                    span=Span(bs.start + m.span.start, bs.start + m.span.end),
                    norm=m.norm,
                )
            )
    # Acronym linkage: an all-caps token whose lowercase matches a known org's
    # suffix-stripped form is that org (ACME ~ "Acme Corp"). Strictly gated to
    # already-detected orgs, so it stays low-noise and deterministic.
    known_orgs = {
        normalize_name(strip_org_suffix(m.text)).replace(" ", "")
        for m in mentions
        if m.etype == "Organization"
    }
    known_orgs.discard("")
    existing_spans = [m.span for m in mentions]
    for bs in block_spans:
        sub = text[bs.start : bs.end]
        for am in _ACRONYM.finditer(sub):
            tok = am.group(0)
            if tok in _ACRONYM_STOP or tok.lower() not in known_orgs:
                continue
            span = Span(bs.start + am.start(), bs.start + am.end())
            if any(span.start < e.end and e.start < span.end for e in existing_spans):
                continue
            mentions.append(
                Mention(text=tok, etype="Organization", span=span, norm=normalize_name(tok))
            )
            existing_spans.append(span)

    mentions.sort(key=lambda x: (x.span.start, x.span.end, x.etype))

    # Canonical entities (merge same type+name), preserving first-seen surface.
    entities: dict[str, Entity] = {}
    for m in mentions:
        eid = entity_id(m.etype, m.text)
        ent = entities.get(eid)
        if ent is None:
            entities[eid] = Entity(entity_id=eid, name=m.text, etype=m.etype, mentions=[m])
        else:
            ent.mentions.append(m)

    coref = _Coref(mentions)
    relations: list[Relation] = []
    linkable = [m for m in mentions if m.etype in ("Organization", "Person")]

    sentences = [s for bs in block_spans for s in segment(text[bs.start : bs.end], bs.start)]
    for s in sentences:
        sub = text[s.start : s.end]
        pol = polarity(sub)
        mod = modality(sub)
        local = _mentions_in(linkable, s)
        sent_mentions = _mentions_in(mentions, s)
        money_m = next((m for m in sent_mentions if m.etype == "Money"), None)
        money_txt = money_m.text if money_m else ""

        for pm in _PRED_RE.finditer(sub):
            surface = pm.group(0)
            canon = canonical_predicate(surface)
            subj_pos = s.start + pm.start()
            obj_pos = s.start + pm.end()
            subj_m = _nearest_before(local, subj_pos)
            obj_m = _nearest_after(local, obj_pos)
            subj_id, subj_inf = _resolve_slot(subj_m, sub, s.start, subj_pos, coref, entities, True)
            obj_id, obj_inf = _resolve_slot(obj_m, sub, s.start, obj_pos, coref, entities, False)
            if not subj_id or not obj_id or subj_id == obj_id:
                continue
            amount = money_txt if canon == "TRANSFERRED" else ""
            relations.append(
                Relation(
                    subject_id=subj_id,
                    predicate=canon,
                    object_id=obj_id,
                    surface=surface.lower(),
                    span=s,
                    polarity=pol,
                    modality=mod,
                    inferred=subj_inf or obj_inf,
                    amount=amount,
                )
            )

        # "wire/transfer/payment from X to Y" (noun form, no verb).
        if _TRANSFER_NOUN.search(sub):
            for fm in _FROM_TO.finditer(sub):
                before = _nearest_before(local, s.start + fm.start("mid")) or _nearest_after(
                    local, s.start + fm.start("mid")
                )
                after = _nearest_after(local, s.start + fm.end())
                if before and after and before is not after:
                    sid = entity_id(before.etype, before.text)
                    oid = entity_id(after.etype, after.text)
                    if sid != oid:
                        relations.append(
                            Relation(
                                subject_id=sid,
                                predicate="TRANSFERRED",
                                object_id=oid,
                                surface="transfer from…to",
                                span=s,
                                polarity=pol,
                                modality=mod,
                                amount=money_txt,
                            )
                        )

    coref.count_coverage(text, block_spans)

    # Deterministic relation order + dedup.
    relations.sort(key=lambda r: (r.subject_id, r.predicate, r.object_id, r.span.start))
    seen: set[tuple[str, str, str, int]] = set()
    deduped: list[Relation] = []
    for r in relations:
        key = (r.subject_id, r.predicate, r.object_id, r.span.start)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return IEResult(
        entities=entities,
        relations=deduped,
        mentions=mentions,
        pronouns_total=coref.total,
        pronouns_resolved=coref.resolved,
    )
