"""MCP surface — expose the L8 query tools to agents.

:mod:`textgraph.mcp.tools` holds the tool specs + dispatcher (no external deps, CI
tested); :mod:`textgraph.mcp.server` is the stdio adapter behind the ``[mcp]`` extra.
"""

from textgraph.mcp.tools import call_tool, tool_names, tool_specs

__all__ = ["call_tool", "tool_names", "tool_specs"]
