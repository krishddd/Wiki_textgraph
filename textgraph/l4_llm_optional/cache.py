"""Prompt→response cache for the L4 LLM pass (reproducibility + cost, G1/G7).

LLM output is non-deterministic, so it is quarantined: it never enters the default
(byte-gated) build, and when enabled it is cached by a content hash of
``(model, system, user, params)``. A warm cache makes an ``--llm`` rebuild
reproducible and free — the same prompt never costs a second call.
"""

from __future__ import annotations

import json
from pathlib import Path

from textgraph.core.content_address import hash_text


class PromptCache:
    """On-disk cache mapping a prompt hash to its response text."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0

    def key(self, model: str, system: str, user: str, temperature: float, max_tokens: int) -> str:
        return hash_text(f"{model}\0{temperature}\0{max_tokens}\0{system}\0{user}")

    def get(self, key: str) -> str | None:
        p = self.dir / f"{key}.json"
        if not p.exists():
            self.misses += 1
            return None
        self.hits += 1
        payload: dict[str, str] = json.loads(p.read_text(encoding="utf-8"))
        return payload["response"]

    def put(self, key: str, response: str) -> None:
        (self.dir / f"{key}.json").write_text(
            json.dumps({"response": response}, ensure_ascii=False), encoding="utf-8"
        )


def _is_cache_entry(p: Path) -> bool:
    """A cache entry is a ``<blake3-hex>.json`` holding a ``response`` — not a build artifact.

    This is what keeps a build-output dir's ``graph.json`` / ``manifest.json`` from being
    miscounted as cached prompts.
    """
    stem = p.stem
    if len(stem) < 32 or not all(c in "0123456789abcdef" for c in stem):
        return False
    try:
        return "response" in json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False


def cache_stats(cache_dir: str | Path) -> dict[str, object]:
    """Report the on-disk warmth of a prompt cache: entry count + total bytes.

    Accepts either the cache directory itself or a build-output directory (it looks for the
    conventional ``llm`` / ``.cache/llm`` beneath it). Only real prompt-cache entries are
    counted (see :func:`_is_cache_entry`), so build artifacts are never mistaken for a warm
    cache. Lets an analyst check — before a key meeting — whether an ``--llm`` rebuild will be
    free (warm) or spend calls (cold). Read-only.
    """
    root = Path(cache_dir)
    # Prefer the conventional LLM-cache locations; fall back to the given dir itself.
    for candidate in (root / "llm", root / ".cache" / "llm", root):
        if candidate.is_dir() and any(_is_cache_entry(p) for p in candidate.glob("*.json")):
            root = candidate
            break
    entries = [p for p in root.glob("*.json") if _is_cache_entry(p)] if root.is_dir() else []
    total_bytes = sum(p.stat().st_size for p in entries)
    return {
        "dir": str(root),
        "exists": root.is_dir(),
        "entries": len(entries),
        "bytes": total_bytes,
        "warm": len(entries) > 0,
    }
