"""Local web console for TextGraph (Phase 6).

A dependency-free, read-only web UI over the L8 QueryEngine — the same typed, cited
tools the CLI and MCP server expose, in a browser. See :mod:`textgraph.console.server`.
"""

from textgraph.console.api import route
from textgraph.console.server import build_engine, serve

__all__ = ["build_engine", "route", "serve"]
