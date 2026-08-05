"""Tokenizer for the TextGraph GQL subset (Phase 7).

Turns a query string into a flat token list for the recursive-descent parser. Pure
and deterministic; whitespace-insensitive; case-insensitive keywords. Recognises the
multi-character graph operators (``->``, ``<-``, ``..``, ``<=``, ``>=``, ``<>``) before
the single-character ones, so ``-[:R]->`` lexes correctly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from textgraph.gql.errors import GQLError

# Reserved words (upper-cased for matching); everything else is an identifier.
KEYWORDS = frozenset(
    {
        "MATCH",
        "WHERE",
        "RETURN",
        "ORDER",
        "BY",
        "ASC",
        "DESC",
        "LIMIT",
        "SKIP",
        "AND",
        "OR",
        "NOT",
        "AS",
        "DISTINCT",
        "CONTAINS",
        "STARTS",
        "ENDS",
        "WITH",
        "TRUE",
        "FALSE",
        "NULL",
        "IN",
    }
)

# Multi-char punctuation first (longest match wins).
_PUNCT = [
    "->",
    "<-",
    "..",
    "<=",
    ">=",
    "<>",
    "=",
    "<",
    ">",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    ":",
    ".",
    ",",
    "*",
    "-",
    "|",
]
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Token:
    kind: str  # "keyword" | "ident" | "string" | "number" | "punct" | "eof"
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    """Lex ``text`` into tokens (trailing EOF sentinel included)."""
    tokens: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in ("'", '"'):  # string literal
            j = i + 1
            buf: list[str] = []
            while j < n and text[j] != ch:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            if j >= n:
                raise GQLError("unterminated string literal", i)
            tokens.append(Token("string", "".join(buf), i))
            i = j + 1
            continue
        m = _NUMBER.match(text, i)
        if m and (ch.isdigit()):
            tokens.append(Token("number", m.group(), i))
            i = m.end()
            continue
        m = _IDENT.match(text, i)
        if m:
            word = m.group()
            kind = "keyword" if word.upper() in KEYWORDS else "ident"
            tokens.append(Token(kind, word.upper() if kind == "keyword" else word, i))
            i = m.end()
            continue
        for p in _PUNCT:
            if text.startswith(p, i):
                tokens.append(Token("punct", p, i))
                i += len(p)
                break
        else:
            raise GQLError(f"unexpected character {ch!r}", i)
    tokens.append(Token("eof", "", n))
    return tokens
