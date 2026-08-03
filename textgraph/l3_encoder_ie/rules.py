"""Deterministic, zero-model entity detection (default L3 backend).

Regex/gazetteer NER tuned for financial-crime corpora: Organizations, Persons,
Money, Accounts, Dates, Emails. Fully deterministic (G1) and CPU-only (G2). The
GLiNER backend (``[ie]`` extra) is a higher-recall drop-in with the same output
shape. Spans are exact canonical-char ranges (G3).
"""

from __future__ import annotations

import re

from textgraph.core.layout import Span
from textgraph.l3_encoder_ie.canonicalize import normalize_name
from textgraph.l3_encoder_ie.model import Mention

# --- entity patterns ---------------------------------------------------------
# Internal tokens exclude '.' so a sentence-ending "Ltd." can't merge the next
# sentence's capitalised words; non-greedy repetition stops at the first suffix.
# Inter-token whitespace allows a single soft line-wrap ("Acme\nCorp") but never a
# blank line, so an entity never spans a paragraph/block boundary.
_H = r"(?:[^\S\n]|\n(?!\n))"
_ORG = re.compile(
    rf"\b([A-Z][A-Za-z0-9&\-]*(?:{_H}+(?:of|and|&|the|for)?{_H}*[A-Z][A-Za-z0-9&\-]*){{0,4}}?"
    rf"{_H}+(?:Corp(?:oration)?|Ltd|Limited|LLC|Inc(?:orporated)?|PLC|GmbH|"
    r"Bank|Group|Holdings?|Trust|Fund|Partners|Co)\.?)\b"
)
_MONEY = re.compile(
    r"(?:USD|EUR|GBP|\$|€|£)\s?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|thousand|bn|m|k)?\b"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|dollars|euros|pounds)\b",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"\baccount\s+(?:number\s+|no\.?\s*)?#?\d{4,}\b|\b[A-Z]{2}\d{2}[A-Z0-9]{8,30}\b",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(?:\d{1,2},?\s+)?\d{4}\b"
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PERSON_CUE = re.compile(
    rf"\b(?:Mr|Mrs|Ms|Dr|Prof)\.?{_H}+([A-Z][a-z]+(?:{_H}+[A-Z][a-z]+){{0,2}})"
    rf"|\b(?:nominee director|director|CEO|officer|owner|suspect|beneficiary){_H}+"
    rf"([A-Z][a-z]+(?:{_H}+[A-Z][a-z]+){{1,2}})",
    re.IGNORECASE,
)
_PERSON_BIGRAM = re.compile(rf"\b([A-Z][a-z]+{_H}+[A-Z][a-z]+)\b")

# Capitalized words that must not start a Person bigram (sentence-initial noise and
# common finance/section vocabulary that is not a personal name).
_PERSON_STOP = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "we",
        "they",
        "it",
        "he",
        "she",
        "our",
        "their",
        "a",
        "an",
        "note",
        "case",
        "report",
        "summary",
        "overview",
        "findings",
        "status",
        "context",
        "decision",
        "consequences",
        "wire",
        "transfer",
        "analysis",
        "investigators",
        "investigator",
        "funds",
        "beneficial",
        "nominee",
        "account",
        "structuring",
        "layering",
        "company",
        "firm",
        "entity",
    }
)
_MONTHS = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)


def _add(mentions: list[Mention], text: str, etype: str, start: int, end: int) -> None:
    surface = text[start:end].strip()
    if not surface:
        return
    # Adjust for stripped leading/trailing whitespace.
    lead = len(text[start:end]) - len(text[start:end].lstrip())
    start += lead
    end = start + len(surface)
    mentions.append(
        Mention(text=surface, etype=etype, span=Span(start, end), norm=normalize_name(surface))
    )


def _overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def extract_entities(text: str) -> list[Mention]:
    """Detect entity mentions in ``text`` with exact canonical-char spans.

    Higher-priority types (Org/Money/Account/Date/Email) claim their spans first;
    Person mentions are only kept where they don't overlap an existing mention.
    """
    mentions: list[Mention] = []

    for m in _MONEY.finditer(text):
        _add(mentions, text, "Money", m.start(), m.end())
    for m in _ACCOUNT.finditer(text):
        _add(mentions, text, "Account", m.start(), m.end())
    for m in _DATE.finditer(text):
        _add(mentions, text, "Date", m.start(), m.end())
    for m in _EMAIL.finditer(text):
        _add(mentions, text, "Email", m.start(), m.end())
    for m in _ORG.finditer(text):
        _add(mentions, text, "Organization", m.start(1), m.end(1))

    high_priority = list(mentions)

    person_spans: list[Mention] = []
    for m in _PERSON_CUE.finditer(text):
        grp = 1 if m.group(1) else 2
        _add(person_spans, text, "Person", m.start(grp), m.end(grp))
    for m in _PERSON_BIGRAM.finditer(text):
        toks = [t.lower() for t in m.group(1).split()]
        if any(t in _PERSON_STOP or t in _MONTHS for t in toks):
            continue
        _add(person_spans, text, "Person", m.start(1), m.end(1))

    existing = high_priority[:]
    for p in person_spans:
        if not any(_overlaps(p.span, e.span) for e in existing):
            mentions.append(p)
            existing.append(p)

    # Deterministic order; drop duplicate spans.
    mentions.sort(key=lambda x: (x.span.start, x.span.end, x.etype))
    deduped: list[Mention] = []
    seen: set[tuple[int, int]] = set()
    for x in mentions:
        key = (x.span.start, x.span.end)
        if key not in seen:
            seen.add(key)
            deduped.append(x)
    return deduped
