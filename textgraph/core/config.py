"""Pinned build configuration + config hashing (G1).

Every layer is a pure function of the layer below it *plus a pinned config hash*.
The config captures the tool version, fixed random seeds, and the flags that alter
extraction (e.g. whether the opt-in LLM pass ran). Its hash is folded into
``manifest.json`` and can be compared across runs to explain any output change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from textgraph import __version__
from textgraph.core.canonical_json import canonical_dump_bytes
from textgraph.core.content_address import blake3_hex


@dataclass(frozen=True)
class Config:
    """Immutable, hashable build configuration.

    Only fields that can change output belong here. Add fields as layers land; the
    hash then naturally distinguishes runs that used different settings.
    """

    tool_version: str = __version__
    # Fixed seeds for every stochastic step (Leiden, blocking, sampling). G1.
    seed: int = 0
    # Local-first by default: the LLM pass (L4) is opt-in (G2).
    llm_enabled: bool = False
    # Hierarchical chunking target (tokens); never fixed 512-token windows.
    chunk_target_tokens: int = 600
    # Free-form, pinned model ids per layer (filled in as layers are added).
    model_pins: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        """Deterministic blake3 hash of the canonical-JSON form of this config."""
        return blake3_hex(canonical_dump_bytes(self.to_dict()))
