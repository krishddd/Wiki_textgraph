"""MCP stdio server exposing the TextGraph query tools (behind the ``[mcp]`` extra).

A thin adapter: it builds a :class:`~textgraph.l8_retrieval.engine.QueryEngine` from a
corpus path (or a prebuilt ``graph.json``) and registers the specs from
:mod:`textgraph.mcp.tools` with a real MCP runtime over stdio. The ``mcp`` package is
imported lazily so importing this module never fails in CI; :func:`build_engine` and
the dispatcher are exercised without it. Run with ``python -m textgraph.mcp.server
<corpus-path>`` once ``pip install 'textgraph[mcp]'`` is present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.mcp.tools import call_tool, tool_specs


def build_engine(source: str | Path) -> QueryEngine:
    """Build a QueryEngine from a corpus directory or a saved ``graph.json`` file."""
    path = Path(source)
    if path.is_file() and path.suffix == ".json":
        return _engine_from_graph_json(path)
    from textgraph.pipeline import build

    result = build(path)
    return QueryEngine(result.nodes, result.edges)


def _engine_from_graph_json(path: Path) -> QueryEngine:
    from textgraph.store.base import ConfidenceTag, Edge, Node, span_from_dict

    doc = json.loads(path.read_text(encoding="utf-8"))
    nodes = [
        Node(
            node_id=n["node_id"],
            labels=tuple(n.get("labels", [])),
            properties=n.get("properties", {}),
        )
        for n in doc.get("nodes", [])
    ]
    edges = [
        Edge(
            edge_id="edge:" + str(i),
            subject=e["subject"],
            predicate=e["predicate"],
            object=e["object"],
            tag=ConfidenceTag(e["tag"]),
            confidence=float(e["confidence"]),
            evidence_count=int(e.get("evidence_count", 0)),
            source_spans=tuple(span_from_dict(s) for s in e.get("source_spans", [])),
            properties=e.get("properties", {}),
        )
        for i, e in enumerate(doc.get("edges", []))
    ]
    return QueryEngine(nodes, edges)


async def _serve(engine: QueryEngine) -> None:  # pragma: no cover - needs [mcp]
    import mcp.types as types
    from mcp.server.stdio import stdio_server

    from mcp.server import Server

    server: Server = Server("textgraph")

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(**spec) for spec in tool_specs()]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def handle_call(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        result = call_tool(engine, name, arguments)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - needs [mcp]
    import asyncio

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m textgraph.mcp.server <corpus-path|graph.json>", file=sys.stderr)
        return 2
    engine = build_engine(args[0])
    asyncio.run(_serve(engine))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
