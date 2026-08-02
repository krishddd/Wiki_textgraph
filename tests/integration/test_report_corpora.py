"""Phase 1 DoD: GRAPH_REPORT.md's '10 suggested questions' must be populated
meaningfully on at least three fixture corpora of different shapes."""

from pathlib import Path

import pytest
from textgraph.l9_artifacts import analytics_lite
from textgraph.l9_artifacts.report import render_report, suggested_questions
from textgraph.pipeline import build

CORPORA = Path(__file__).parent.parent / "fixtures" / "corpora"
SHAPES = ["docs", "adr", "chat"]


@pytest.mark.parametrize("shape", SHAPES)
def test_report_has_ten_grounded_questions(shape: str) -> None:
    result = build(CORPORA / shape)
    assert result.nodes, f"{shape}: no nodes built"
    diag = analytics_lite.compute(result.nodes, result.edges)
    questions = suggested_questions(result.nodes, result.edges, diag)

    assert len(questions) == 10, f"{shape}: expected 10 questions, got {len(questions)}"
    assert len(set(questions)) == 10, f"{shape}: questions must be unique"
    assert all(q.endswith("?") for q in questions)


@pytest.mark.parametrize("shape", SHAPES)
def test_report_renders_and_is_deterministic(shape: str) -> None:
    result = build(CORPORA / shape)
    diag = analytics_lite.compute(result.nodes, result.edges)
    a = render_report(
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
        diag=diag,
        config_hash=result.config_hash,
    )
    b = render_report(
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
        diag=diag,
        config_hash=result.config_hash,
    )
    assert a == b
    assert "## 10 questions this graph can answer well" in a


def test_adr_surfaces_rationale_and_requirements() -> None:
    result = build(CORPORA / "adr")
    labels = {label for n in result.nodes for label in n.labels}
    assert "Rationale" in labels
    assert "Requirement" in labels


def test_chat_surfaces_participants() -> None:
    result = build(CORPORA / "chat")
    labels = {label for n in result.nodes for label in n.labels}
    assert "Participant" in labels
    assert "Message" in labels
