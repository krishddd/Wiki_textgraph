"""Splink (Fellegi-Sunter) scoring backend — optional, ``[er]`` extra.

Splink runs probabilistic record linkage on DuckDB (in-process, local), producing
calibrated match weights. Import-guarded so the default install never requires it;
when absent, :func:`score_pairs_splink` raises ``UnsupportedFormat`` and the resolver
uses the deterministic rule scorer.
"""

from __future__ import annotations

from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l5_entity_resolution.model import ERecord


def is_available() -> bool:
    try:
        import splink  # noqa: F401
    except ImportError:
        return False
    return True


def score_pairs_splink(
    records_by_id: dict[str, ERecord], pairs: list[tuple[str, str]]
) -> list[tuple[str, str, float]]:
    """Score candidate pairs with Splink. Requires ``textgraph[er]``.

    The DuckDB/EM training wiring lands with the storage backend (Phase 4); until
    then this raises clearly and callers fall back to backend='rules'.
    """
    if not is_available():
        raise UnsupportedFormat("Splink backend needs an extra: install 'textgraph[er]'")
    raise UnsupportedFormat("Splink backend is not wired to DuckDB yet; use backend='rules'")
