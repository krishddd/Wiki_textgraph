"""GQL errors (Phase 7).

A single error type for both parse and execution failures, carrying the character
offset so callers can point at the offending token. Kept separate so the parser,
engine, and CLI can all raise/catch the same thing.
"""

from __future__ import annotations


class GQLError(ValueError):
    """A GQL parse or execution error, optionally anchored to a source position."""

    def __init__(self, message: str, pos: int | None = None) -> None:
        self.pos = pos
        super().__init__(message if pos is None else f"{message} (at position {pos})")
