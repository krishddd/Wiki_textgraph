"""Structural role similarity — the deterministic shell-pattern detector (not Node2Vec)."""

from pathlib import Path

from textgraph.l7_analytics.roles import compute_signatures, role_similarity
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

# Two controllers each fanning money to three fronts (identical shape, disjoint names),
# plus an entity with a different role.
SHELL = """# Case

John Smith controls Acme Holdings.
Acme Holdings transferred $1,000,000 to Front One.
Acme Holdings transferred $2,000,000 to Front Two.
Acme Holdings transferred $3,000,000 to Front Three.

Mary Jones controls Zenith Group.
Zenith Group transferred $1,500,000 to Shell Alpha.
Zenith Group transferred $2,500,000 to Shell Beta.
Zenith Group transferred $3,500,000 to Shell Gamma.

Bob Lee is director of Ordinary LLC.
Ordinary LLC associated with Partner Co.
"""


def _engine(tmp_path: Path) -> QueryEngine:
    d = tmp_path / "c"
    d.mkdir()
    (d / "f.md").write_text(SHELL, encoding="utf-8")
    r = build(d)
    return QueryEngine(r.nodes, r.edges)


def test_structural_twin_ranks_first(tmp_path: Path) -> None:
    # Zenith Group has the same role as Acme Holdings (controller -> 3 fronts) despite sharing
    # no name/document/neighbor -> it must be the top match. This is role, not proximity.
    res = _engine(tmp_path).similar_roles("Acme Holdings", k=5)
    assert res["found"]
    assert res["matches"], "should find structural peers"
    assert res["matches"][0]["name"] == "Zenith Group"
    assert res["matches"][0]["similarity"] > 0.9


def test_role_matches_are_interpretable(tmp_path: Path) -> None:
    res = _engine(tmp_path).similar_roles("Acme Holdings", k=5)
    top = res["matches"][0]
    assert "TRANSFERRED" in top["top_relations"]  # its dominant relation, explaining the match
    assert top["total_degree"] >= 1


def test_similar_roles_is_deterministic(tmp_path: Path) -> None:
    eng = _engine(tmp_path)
    a = eng.similar_roles("Acme Holdings", k=8)
    b = eng.similar_roles("Acme Holdings", k=8)
    assert a == b  # no RNG, no training -> byte-identical ranking


def test_missing_anchor_returns_not_found(tmp_path: Path) -> None:
    res = _engine(tmp_path).similar_roles("Nonexistent Ltd")
    assert res["found"] is False
    assert res["matches"] == []


def test_node2vec_backend_falls_back_cleanly_without_the_extra(tmp_path: Path) -> None:
    # Asking for node2vec without the [graph] extra must degrade to the deterministic backend
    # with an explanatory note, never a stack trace.
    import importlib.util

    res = _engine(tmp_path).similar_roles("Acme Holdings", k=3, backend="node2vec")
    assert res["found"]
    if importlib.util.find_spec("node2vec") is None:
        assert res["backend"] == "deterministic"
        assert "[graph]" in res["note"]
        assert res["matches"]  # still returns useful (deterministic) results


def test_node2vec_backend_when_available(tmp_path: Path) -> None:
    import pytest

    pytest.importorskip("node2vec")
    res = _engine(tmp_path).similar_roles("Acme Holdings", k=3, backend="node2vec")
    assert res["found"] and res["backend"] == "node2vec"
    assert all("similarity" in m for m in res["matches"])


def test_signatures_capture_the_shell_shape(tmp_path: Path) -> None:
    d = tmp_path / "c"
    d.mkdir()
    (d / "f.md").write_text(SHELL, encoding="utf-8")
    r = build(d)
    sigs = compute_signatures(r.nodes, r.edges)
    # Resolve the two controllers by name.
    acme = next(s for s in sigs.values() if s.name == "Acme Holdings")
    zenith = next(s for s in sigs.values() if s.name == "Zenith Group")
    # Both are high-out-degree controllers.
    assert acme.scalars["out_degree"] >= 3
    assert zenith.scalars["out_degree"] >= 3
    # Their raw signatures are near-identical in shape -> cosine ~ 1.
    ranked = role_similarity(sigs, acme.node_id, k=1)
    assert ranked[0]["node_id"] == zenith.node_id
