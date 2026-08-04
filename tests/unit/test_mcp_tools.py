"""MCP tool surface: specs are well-formed and dispatch to the engine."""

from pathlib import Path

import pytest
from textgraph.l8_retrieval import QueryEngine
from textgraph.mcp import call_tool, tool_names, tool_specs
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _engine() -> QueryEngine:
    result = build(DOCS)
    return QueryEngine(result.nodes, result.edges)


def test_tool_specs_are_well_formed() -> None:
    specs = tool_specs()
    assert {t["name"] for t in specs} == {
        "search",
        "neighbors",
        "path",
        "why",
        "timeline",
        "contradictions",
        "communities",
        "stats",
    }
    for spec in specs:
        assert spec["description"]
        assert spec["inputSchema"]["type"] == "object"


def test_dispatch_every_tool_returns_serialisable_dict() -> None:
    qe = _engine()
    calls = {
        "search": {"query": "funds", "k": 3},
        "neighbors": {"node": "Acme Corp"},
        "path": {"source": "Acme Corp", "target": "Gamma Holdings"},
        "why": {"node": "Acme Corp"},
        "timeline": {"node": "Acme Corp"},
        "contradictions": {},
        "communities": {},
        "stats": {},
    }
    assert set(calls) == set(tool_names())
    for name, args in calls.items():
        result = call_tool(qe, name, args)
        assert isinstance(result, dict)
        assert result["tool"] == name


def test_unknown_tool_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        call_tool(_engine(), "nonesuch", {})
