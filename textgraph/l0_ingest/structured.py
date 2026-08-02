"""Structured-data ingestor (L0): JSON / YAML / TOML.

Parses with real parsers (stdlib ``json``/``tomllib``, PyYAML), then emits a FIELD
block per leaf path (``$.a.b[0]``). Spans are located deterministically by scanning
the canonical text for each key in document order; when a key can't be pinned, the
block falls back to the whole-document span (still a valid, re-verifiable range).
"""

from __future__ import annotations

import json
import tomllib
from typing import Any

import yaml

from textgraph.core.layout import Block, BlockKind, IngestResult, Span
from textgraph.l0_ingest.base import canonical_for, make_chunks, register


class _KeyLocator:
    """Forward-scanning locator: finds each key's next occurrence deterministically."""

    def __init__(self, text: str) -> None:
        self._text = text

    def locate(self, key: str, from_pos: int) -> tuple[int, int]:
        if key:
            idx = self._text.find(key, from_pos)
            if idx == -1:
                idx = self._text.find(key)
            if idx != -1:
                return idx, idx + len(key)
        return 0, len(self._text)


def _leaf_blocks(data: Any, locator: _KeyLocator, text_len: int) -> list[Block]:
    blocks: list[Block] = []
    cursor = 0

    def walk(node: Any, path: str) -> None:
        nonlocal cursor
        if isinstance(node, dict):
            for key in node:
                start, end = locator.locate(str(key), cursor)
                cursor = end
                walk(node[key], f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")
        else:
            value = "" if node is None else str(node)
            start, end = locator.locate(value[:60], cursor) if value else (0, text_len)
            blocks.append(
                Block(
                    BlockKind.FIELD,
                    Span(start, end),
                    f"{path.lstrip('.')} = {value}",
                    props={"path": path.lstrip("."), "value": value},
                )
            )

    walk(data, "")
    return blocks


def _ingest_structured(raw: bytes, source_name: str, fmt: str, data: Any) -> IngestResult:
    canonical = canonical_for(raw, source_name)
    text = canonical.text
    locator = _KeyLocator(text)
    blocks = _leaf_blocks(data, locator, len(text))
    chunks = make_chunks(canonical.doc_id, text, blocks)
    return IngestResult(
        canonical=canonical,
        raw=raw,
        source_path=source_name,
        format=fmt,
        blocks=blocks,
        chunks=chunks,
    )


@register(".json")
def ingest_json(raw: bytes, source_name: str) -> IngestResult:
    data = json.loads(canonical_for(raw, source_name).text)
    return _ingest_structured(raw, source_name, "json", data)


@register(".yaml", ".yml")
def ingest_yaml(raw: bytes, source_name: str) -> IngestResult:
    data = yaml.safe_load(canonical_for(raw, source_name).text)
    return _ingest_structured(raw, source_name, "yaml", data)


@register(".toml")
def ingest_toml(raw: bytes, source_name: str) -> IngestResult:
    data = tomllib.loads(canonical_for(raw, source_name).text)
    return _ingest_structured(raw, source_name, "toml", data)
