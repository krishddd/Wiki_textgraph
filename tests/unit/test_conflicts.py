"""Conflict detection — single-truth truth discovery, surfaced never silently merged."""

from pathlib import Path

import pytest
from textgraph.core.config import Config
from textgraph.core.content_address import verify_span_hash
from textgraph.l6_graph_model.conflicts import detect_conflicts
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

CONFLICT = Path(__file__).parent.parent / "fixtures" / "corpora" / "conflict"


def _write(tmp_path: Path, **files: str) -> Path:
    for name, text in files.items():
        (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")
    return tmp_path


def _conflicts(nodes: list) -> list:
    return [n for n in nodes if "Conflict" in n.labels]


# --- detection ---------------------------------------------------------------


def test_cross_document_single_truth_conflict_is_detected() -> None:
    r = build(CONFLICT)
    confs = _conflicts(r.nodes)
    preds = sorted(n.properties["predicate"] for n in confs)
    # Acme controls Beta (A) vs Gamma (B); owns Delta (A) vs Omega (B) — both single-truth.
    assert preds == ["BENEFICIAL_OWNER_OF", "CONTROLS"]
    assert all(n.properties["severity"] == "HIGH" for n in confs)  # legally consequential
    assert r.graph_stats["conflicts"] == 2


def test_contends_edges_are_cited_and_reverify() -> None:
    r = build(CONFLICT)
    raw_by_doc = {ir.doc_id: ir.raw for ir in r.results}
    contends = [e for e in r.edges if e.predicate == "CONTENDS"]
    assert contends
    for e in contends:
        assert str(e.tag) == "INFERRED"  # never GENERATED
        assert e.source_spans
        for s in e.source_spans:
            assert verify_span_hash(raw_by_doc[s.doc_id], s.start, s.end, s.hash)


def test_sequential_role_change_is_not_a_conflict(tmp_path: Path) -> None:
    # A single-truth value that changes over time (Beta then Gamma) is NOT a conflict:
    # the later dated claim closes the earlier one's window, so they don't overlap (§1.4).
    root = _write(
        tmp_path,
        a="On 2019-01-01, Acme Corp controls Beta Ltd.",
        b="On 2021-01-01, Acme Corp controls Gamma Holdings.",
    )
    r = build(root)
    assert _conflicts(r.nodes) == []


def test_contemporaneous_claims_are_a_conflict(tmp_path: Path) -> None:
    # Same date, different objects -> genuinely overlapping -> a conflict.
    root = _write(
        tmp_path,
        a="On 2020-01-01, Acme Corp controls Beta Ltd.",
        b="On 2020-01-01, Acme Corp controls Gamma Holdings.",
    )
    r = build(root)
    assert len(_conflicts(r.nodes)) == 1


def test_multi_truth_predicate_is_not_flagged(tmp_path: Path) -> None:
    # TRANSFERRED is multi-truth (many transfers are fine) -> no conflict.
    root = _write(
        tmp_path,
        a="Acme Corp transferred $1 to Beta Ltd. Acme Corp transferred $2 to Gamma Holdings.",
    )
    r = build(root)
    assert _conflicts(r.nodes) == []


def test_severity_medium_for_director_of() -> None:
    from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

    span = SourceSpan(doc_id="d", start=0, end=1, hash="h")
    nodes = [
        Node("claim:1", ("Claim",), {"subject": "x", "predicate": "DIRECTOR_OF", "object": "a"}),
        Node("claim:2", ("Claim",), {"subject": "x", "predicate": "DIRECTOR_OF", "object": "b"}),
    ]
    edges = [
        Edge("e1", "x", "SUBJECT_OF", "claim:1", ConfidenceTag.INFERRED, 1.0, 1, (span,)),
        Edge("e2", "x", "SUBJECT_OF", "claim:2", ConfidenceTag.INFERRED, 1.0, 1, (span,)),
    ]
    cnodes, _cedges = detect_conflicts(nodes, edges)
    assert len(cnodes) == 1
    assert cnodes[0].properties["severity"] == "MEDIUM"


def test_empty_single_truth_set_detects_nothing() -> None:
    r = build(CONFLICT)
    cnodes, cedges = detect_conflicts(r.nodes, r.edges, single_truth=())
    assert cnodes == [] and cedges == []


def test_config_flag_disables_detection(tmp_path: Path) -> None:
    root = _write(tmp_path, a="Acme Corp controls Beta Ltd. Acme Corp controls Gamma Holdings.")
    r = build(root, config=Config(detect_conflicts=False))
    assert _conflicts(r.nodes) == []
    assert r.graph_stats["conflicts"] == 0


def test_detection_is_deterministic() -> None:
    r = build(CONFLICT)
    first = detect_conflicts(r.nodes, r.edges)
    second = detect_conflicts(r.nodes, r.edges)
    assert [n.node_id for n in first[0]] == [n.node_id for n in second[0]]
    assert [e.edge_id for e in first[1]] == [e.edge_id for e in second[1]]


# --- engine surface ----------------------------------------------------------


def test_engine_conflicts_returns_cited_views() -> None:
    r = build(CONFLICT)
    res = QueryEngine(r.nodes, r.edges).conflicts().to_dict()
    assert res["tool"] == "conflicts"
    assert len(res["conflicts"]) == 2
    for c in res["conflicts"]:
        assert c["severity"] == "HIGH"
        assert c["subject"] == "Acme Corp"
        assert len(c["objects"]) == 2
        assert len(c["claims"]) == 2
        assert all(claim["citations"] for claim in c["claims"])  # every contending claim cited


def test_engine_conflicts_empty_when_none(tmp_path: Path) -> None:
    root = _write(tmp_path, a="Acme Corp controls Beta Ltd.")
    r = build(root)
    assert QueryEngine(r.nodes, r.edges).conflicts().to_dict()["conflicts"] == []


# --- CLI ---------------------------------------------------------------------


def test_conflicts_cli_lists_them(capsys: pytest.CaptureFixture[str]) -> None:
    from textgraph.cli import main

    assert main(["conflicts", str(CONFLICT)]) == 0
    out = capsys.readouterr().out
    assert "conflicts: 2" in out
    assert "HIGH" in out and "CONTROLS" in out


def test_conflicts_cli_none(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from textgraph.cli import main

    _write(tmp_path, a="Acme Corp controls Beta Ltd.")
    assert main(["conflicts", str(tmp_path)]) == 0
    assert "no conflicts found" in capsys.readouterr().out


def test_conflicts_cli_missing_path() -> None:
    from textgraph.cli import main

    assert main(["conflicts", str(CONFLICT / "nope")]) == 2
