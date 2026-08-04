"""Console routing — a pure function from request to response (testable, no socket).

The ``textgraph console`` web UI is a thin local shell over the L8 ``QueryEngine`` and
the same ``call_tool`` dispatcher the MCP server uses (G6 — one query surface, many
formatters). Keeping :func:`route` free of any HTTP/socket machinery means the whole
API is unit-testable in CI; :mod:`textgraph.console.server` just wires it to
``http.server``. Read-only: the console never mutates the graph.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from textgraph.console.page import render_page
from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.mcp.tools import call_tool, tool_specs

# Which query-string params each tool accepts, and how to coerce them.
_TOOL_PARAMS: dict[str, dict[str, type]] = {
    "search": {"query": str, "k": int, "max_tokens": int},
    "neighbors": {"node": str, "k": int},
    "path": {"source": str, "target": str, "k": int},
    "why": {"node": str},
    "timeline": {"node": str},
    "contradictions": {},
    "communities": {},
    "stats": {},
}


def _coerce(tool: str, params: dict[str, str]) -> dict[str, Any]:
    spec = _TOOL_PARAMS.get(tool, {})
    args: dict[str, Any] = {}
    for name, caster in spec.items():
        if name in params and params[name] != "":
            with contextlib.suppress(TypeError, ValueError):
                args[name] = caster(params[name])
    return args


def _json(status: int, payload: Any) -> tuple[int, str, bytes]:
    return status, "application/json", json.dumps(payload, ensure_ascii=False).encode("utf-8")


def route(engine: QueryEngine, path: str, params: dict[str, str]) -> tuple[int, str, bytes]:
    """Map a request ``(path, query params)`` to ``(status, content_type, body)``."""
    if path in ("/", "/index.html"):
        return 200, "text/html; charset=utf-8", render_page().encode("utf-8")
    if path == "/api/tools":
        return _json(200, {"tools": tool_specs()})
    if path == "/api/graph":
        max_nodes = 600
        with contextlib.suppress(TypeError, ValueError):
            max_nodes = int(params.get("max_nodes", "600"))
        return _json(200, engine.graph_view(max_nodes=max_nodes))
    if path == "/api/call":
        tool = params.get("tool", "")
        if tool not in _TOOL_PARAMS:
            return _json(400, {"error": f"unknown tool: {tool}"})
        try:
            result = call_tool(engine, tool, _coerce(tool, params))
        except KeyError as exc:
            return _json(400, {"error": f"missing required argument: {exc}"})
        except Exception as exc:  # pragma: no cover - defensive; surface as 500
            return _json(500, {"error": str(exc)})
        return _json(200, result)
    return _json(404, {"error": "not found"})
