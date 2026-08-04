"""MCP tool definitions over the L8 QueryEngine (backend-agnostic).

This module is the single source of truth for the agent-facing tool surface: the
JSON-schema tool specs *and* the dispatcher that runs a call against a
:class:`~textgraph.l8_retrieval.engine.QueryEngine`. It has no dependency on the
``mcp`` package, so it is fully unit-testable in CI without the ``[mcp]`` extra;
:mod:`textgraph.mcp.server` is the thin stdio adapter that registers these with a
real MCP runtime (G6 — an agent queries typed tools, never raw Cypher).
"""

from __future__ import annotations

from typing import Any

from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.l8_retrieval.model import as_dict

_STRING = {"type": "string"}


def tool_specs() -> list[dict[str, Any]]:
    """The eight typed tools, as MCP-style ``{name, description, inputSchema}`` dicts."""
    return [
        {
            "name": "search",
            "description": (
                "Hybrid BM25 + graph (Personalized PageRank) search. Returns bounded, "
                "cited chunk + entity hits with local/global routing."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": _STRING,
                    "k": {"type": "integer", "minimum": 1, "default": 5},
                    "max_tokens": {"type": "integer", "minimum": 128, "default": 1500},
                },
                "required": ["query"],
            },
        },
        {
            "name": "neighbors",
            "description": "1-hop typed neighbors of an entity (by id or name), cited.",
            "inputSchema": {
                "type": "object",
                "properties": {"node": _STRING, "k": {"type": "integer", "default": 20}},
                "required": ["node"],
            },
        },
        {
            "name": "path",
            "description": (
                "Up to k maximum-likelihood paths between two entities "
                "(shortest under -log(confidence)), with cited steps."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": _STRING,
                    "target": _STRING,
                    "k": {"type": "integer", "default": 1},
                },
                "required": ["source", "target"],
            },
        },
        {
            "name": "why",
            "description": "Cited claims (and rationale) explaining an entity's role.",
            "inputSchema": {
                "type": "object",
                "properties": {"node": _STRING},
                "required": ["node"],
            },
        },
        {
            "name": "timeline",
            "description": "Claims about an entity ordered by temporal validity (t_valid).",
            "inputSchema": {
                "type": "object",
                "properties": {"node": _STRING},
                "required": ["node"],
            },
        },
        {
            "name": "contradictions",
            "description": "All detected contradictions (opposite-polarity claim pairs), cited.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "communities",
            "description": "Detected communities with auto-generated labels and top members.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "stats",
            "description": "Graph counts and the most central entities.",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def tool_names() -> list[str]:
    return [t["name"] for t in tool_specs()]


def call_tool(engine: QueryEngine, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one tool call to the engine and return its JSON-serialisable result."""
    args = arguments or {}
    if name == "search":
        return as_dict(
            engine.search(
                str(args["query"]),
                k=int(args.get("k", 5)),
                max_tokens=int(args.get("max_tokens", 1500)),
            )
        )
    if name == "neighbors":
        return as_dict(engine.neighbors(str(args["node"]), k=int(args.get("k", 20))))
    if name == "path":
        return as_dict(
            engine.path(str(args["source"]), str(args["target"]), k=int(args.get("k", 1)))
        )
    if name == "why":
        return as_dict(engine.why(str(args["node"])))
    if name == "timeline":
        return as_dict(engine.timeline(str(args["node"])))
    if name == "contradictions":
        return as_dict(engine.contradictions())
    if name == "communities":
        return as_dict(engine.communities())
    if name == "stats":
        return as_dict(engine.stats())
    raise ValueError(f"unknown tool: {name}")
