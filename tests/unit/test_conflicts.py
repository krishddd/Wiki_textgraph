"""Conflict detection — single-truth truth discovery, surfaced never silently merged."""

from pathlib import Path

import pytest
from textgraph.core.config import Config
from textgraph.core.content_address import verify_span_hash
from textgraph.l6_graph_model.conflicts import detect_conflicts, resolve_conflicts
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build, build_graph_bytes

CONFLICT = Path(__file__).parent.parent / "fixtures" / "corpora" / "conflict"


def _write(tmp_path: Path, **files: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
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


# --- resolution (opt-in, never destructive) ----------------------------------


def _two_vs_one(tmp_path: Path) -> Path:
    """Beta asserted by two undated sources, Gamma by one — a resolvable conflict."""
    return _write(
        tmp_path,
        a="Acme Corp controls Beta Ltd.",
        b="Acme Corp controls Beta Ltd.",
        c="Acme Corp controls Gamma Holdings.",
    )


def _winner_name(r: object) -> str | None:
    conf = next(n for n in r.nodes if "Conflict" in n.labels)  # type: ignore[attr-defined]
    ro = conf.properties.get("resolved_object")
    name = {n.node_id: n.properties.get("name") for n in r.nodes}  # type: ignore[attr-defined]
    return name.get(ro) if ro else None


def test_voting_picks_the_best_supported_object(tmp_path: Path) -> None:
    r = build(_two_vs_one(tmp_path), config=Config(resolve_conflicts_strategy="voting"))
    assert _winner_name(r) == "Beta Ltd"  # 2 sources beat 1


def test_credibility_weighting_can_flip_the_winner(tmp_path: Path) -> None:
    # Gamma's lone source outweighs Beta's two once it's credited 10x.
    cfg = Config(
        resolve_conflicts_strategy="credibility_weighted", source_credibility={"c.md": 10.0}
    )
    r = build(_two_vs_one(tmp_path), config=cfg)
    assert _winner_name(r) == "Gamma Holdings"


def test_most_recent_is_unresolved_when_undated(tmp_path: Path) -> None:
    r = build(_two_vs_one(tmp_path), config=Config(resolve_conflicts_strategy="most_recent"))
    conf = next(n for n in r.nodes if "Conflict" in n.labels)
    assert conf.properties.get("resolved_object") is None
    assert "unresolved" in conf.properties.get("resolution_note", "")
    assert not [e for e in r.edges if e.predicate == "SUPERSEDED_BY"]


def test_resolution_is_non_destructive(tmp_path: Path) -> None:
    r = build(_two_vs_one(tmp_path), config=Config(resolve_conflicts_strategy="voting"))
    superseded = [e for e in r.edges if e.predicate == "SUPERSEDED_BY"]
    assert len(superseded) == 1  # the one Gamma claim demoted
    e = superseded[0]
    assert str(e.tag) == "INFERRED" and e.source_spans  # cited, not GENERATED, not deleted
    # The losing claim node survives, tagged with the pointer to the winner.
    loser = next(n for n in r.nodes if n.node_id == e.subject)
    assert loser.properties.get("superseded_by") == e.object
    assert loser.properties.get("resolved_by") == "voting"
    # Its original direct CONTROLS edge is untouched (never deleted).
    assert any(x.predicate == "CONTROLS" for x in r.edges)


def test_unknown_strategy_raises() -> None:
    r = build(CONFLICT)
    with pytest.raises(ValueError, match="unknown resolution strategy"):
        resolve_conflicts(r.nodes, r.edges, strategy="bogus")


def test_resolution_is_deterministic() -> None:
    cfg = Config(resolve_conflicts_strategy="voting")
    assert build_graph_bytes(CONFLICT, config=cfg) == build_graph_bytes(CONFLICT, config=cfg)


def test_engine_surfaces_resolution(tmp_path: Path) -> None:
    r = build(_two_vs_one(tmp_path), config=Config(resolve_conflicts_strategy="voting"))
    (view,) = QueryEngine(r.nodes, r.edges).conflicts().to_dict()["conflicts"]
    assert view["resolved"] is True
    assert view["resolved_object"] == "Beta Ltd"
    assert view["resolution_strategy"] == "voting"


def test_build_cli_resolve_conflicts_flag(tmp_path: Path) -> None:
    from textgraph.cli import main

    corpus = _two_vs_one(tmp_path / "c")
    out = tmp_path / "graph.json"
    argv = ["build", str(corpus), "--json-only", str(out), "--resolve-conflicts", "voting"]
    assert main(argv) == 0
    import json

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert any(e["predicate"] == "SUPERSEDED_BY" for e in doc["edges"])


def test_conflicts_cli_resolve_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from textgraph.cli import main

    corpus = _two_vs_one(tmp_path)
    assert main(["conflicts", str(corpus), "--resolve", "voting"]) == 0
    out = capsys.readouterr().out
    assert "resolved by voting" in out
    assert "winner: Beta Ltd" in out
