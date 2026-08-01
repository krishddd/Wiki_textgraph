"""Run-length-encoded offset maps (G3).

When raw bytes are normalized into canonical UTF-8 text, character positions in
the canonical text no longer line up with byte positions in the raw input
(multi-byte UTF-8, CRLF->LF collapse, BOM stripping, ...). To keep every citation
re-verifiable, we record a mapping from *canonical character index* to *raw byte
offset*, run-length encoded so it stays compact for typical documents.

A citation stores a canonical char span; provenance verification maps it back to
a raw byte span via this map and re-hashes the original bytes.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OffsetRun:
    """A maximal run of canonical chars whose raw byte offset advances by a
    constant ``delta`` per character.

    For a canonical index ``c`` in ``[canonical_start, canonical_start + length]``:
        raw_offset(c) = raw_start + (c - canonical_start) * delta

    Most runs are plain ASCII/1-byte text (``delta == 1``). A CRLF that collapses
    to a single ``\\n`` becomes a length-1 run with ``delta == 2``; a 3-byte UTF-8
    character becomes a run with ``delta == 3``; and so on.
    """

    canonical_start: int
    raw_start: int
    length: int
    delta: int


class OffsetMap:
    """Maps canonical character indices to raw byte offsets.

    The map is total over ``[0, canonical_len]`` (inclusive upper bound so that an
    exclusive span end can be mapped). It is built via :meth:`from_char_byte_lengths`
    during normalization and is fully serializable for byte-stable artifacts (G1).
    """

    __slots__ = ("_canonical_len", "_raw_len", "_runs", "_starts")

    def __init__(self, runs: list[OffsetRun], canonical_len: int, raw_len: int) -> None:
        self._runs = runs
        self._starts = [r.canonical_start for r in runs]
        self._canonical_len = canonical_len
        self._raw_len = raw_len

    @property
    def canonical_len(self) -> int:
        return self._canonical_len

    @property
    def raw_len(self) -> int:
        return self._raw_len

    @property
    def runs(self) -> list[OffsetRun]:
        return list(self._runs)

    @classmethod
    def from_char_byte_lengths(
        cls, byte_lengths: list[int], raw_len: int, *, raw_start: int = 0
    ) -> OffsetMap:
        """Build a map from the per-character raw-byte length of each canonical char.

        ``byte_lengths[i]`` is how many raw bytes canonical character ``i`` consumed.
        Consecutive characters with equal byte length are grouped into one run.
        ``raw_start`` accounts for leading raw bytes that belong to no canonical
        character (e.g. a stripped BOM), so ``to_raw(0)`` points past them.
        """
        runs: list[OffsetRun] = []
        raw_pos = raw_start
        i = 0
        n = len(byte_lengths)
        while i < n:
            delta = byte_lengths[i]
            run_start = i
            raw_run_start = raw_pos
            while i < n and byte_lengths[i] == delta:
                raw_pos += byte_lengths[i]
                i += 1
            runs.append(
                OffsetRun(
                    canonical_start=run_start,
                    raw_start=raw_run_start,
                    length=i - run_start,
                    delta=delta,
                )
            )
        return cls(runs, canonical_len=n, raw_len=raw_len)

    def to_raw(self, canonical_index: int) -> int:
        """Map a single canonical char index to its raw byte offset.

        ``canonical_index`` may equal ``canonical_len`` (exclusive span end), which
        maps to ``raw_len``.
        """
        if canonical_index < 0 or canonical_index > self._canonical_len:
            raise IndexError(
                f"canonical index {canonical_index} out of range [0, {self._canonical_len}]"
            )
        if canonical_index == self._canonical_len:
            return self._raw_len
        # Rightmost run whose canonical_start <= canonical_index.
        run = self._runs[bisect_right(self._starts, canonical_index) - 1]
        return run.raw_start + (canonical_index - run.canonical_start) * run.delta

    def to_raw_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a canonical char span ``[start, end)`` to a raw byte span ``[b0, b1)``."""
        if start > end:
            raise ValueError(f"start ({start}) must be <= end ({end})")
        return self.to_raw(start), self.to_raw(end)

    def to_dict(self) -> dict[str, Any]:
        """Serializable form (used inside byte-stable graph artifacts)."""
        return {
            "canonical_len": self._canonical_len,
            "raw_len": self._raw_len,
            "runs": [[r.canonical_start, r.raw_start, r.length, r.delta] for r in self._runs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OffsetMap:
        runs = [
            OffsetRun(canonical_start=r[0], raw_start=r[1], length=r[2], delta=r[3])
            for r in data["runs"]
        ]
        return cls(
            runs,
            canonical_len=int(data["canonical_len"]),
            raw_len=int(data["raw_len"]),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OffsetMap):
            return NotImplemented
        return (
            self._runs == other._runs
            and self._canonical_len == other._canonical_len
            and self._raw_len == other._raw_len
        )

    def __repr__(self) -> str:
        return (
            f"OffsetMap(runs={len(self._runs)}, "
            f"canonical_len={self._canonical_len}, raw_len={self._raw_len})"
        )
