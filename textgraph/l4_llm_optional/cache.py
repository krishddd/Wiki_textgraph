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
