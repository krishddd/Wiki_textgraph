"""Allen interval algebra over bi-temporal claims."""

from pathlib import Path

from textgraph.l6_graph_model.allen import (
    RELATIONS,
    allen_relation,
    interval_of,
    pairwise_relations,
)
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

TEMPORAL = Path(__file__).parent.parent / "fixtures" / "corpora" / "temporal"


def _iv(start, end):
    return interval_of({"t_valid": start, "t_invalid": end})


def test_thirteen_relations_defined() -> None:
    assert len(RELATIONS) == 13


def test_seven_base_relations() -> None:
    cases = {
        "before": (_iv("2020-01", "2020-02"), _iv("2020-03", "2020-04")),
        "meets": (_iv("2020-01", "2020-03"), _iv("2020-03", "2020-04")),
        "overlaps": (_iv("2020-01", "2020-03-15"), _iv("2020-03", "2020-04")),
        "during": (_iv("2020-03-05", "2020-03-10"), _iv("2020-03", "2020-04")),
        "starts": (_iv("2020-03", "2020-03-10"), _iv("2020-03", "2020-04")),
        "finishes": (_iv("2020-03-20", "2020-04"), _iv("2020-03", "2020-04")),
        "equals": (_iv("2020-03", "2020-04"), _iv("2020-03", "2020-04")),
    }
    for expect, (a, b) in cases.items():
        assert allen_relation(a, b) == expect, expect


def test_inverses_are_symmetric() -> None:
    a, b = _iv("2020-01", "2020-02"), _iv("2020-03", "2020-04")
    assert allen_relation(a, b) == "before"
    assert allen_relation(b, a) == "after"  # the inverse
    c, d = _iv("2020-01", "2020-05"), _iv("2020-02", "2020-04")
    assert allen_relation(c, d) == "contains"
    assert allen_relation(d, c) == "during"


def test_open_ended_intervals_use_infinity() -> None:
    # A still-valid claim (no t_invalid) that began earlier contains a closed one.
    still_open = _iv("2020-01", None)
    closed = _iv("2020-03", "2020-04")
    assert allen_relation(still_open, closed) == "contains"
    # Two never-invalidated claims with the same start are equal (+inf == +inf).
    assert allen_relation(_iv("2020-01", None), _iv("2020-01", None)) == "equals"


def test_pairwise_skips_undated_and_before_after_by_default() -> None:
    claims = [
        {"id": "a", "label": "A", "t_valid": "2020-01", "t_invalid": "2020-03"},
        {"id": "b", "label": "B", "t_valid": "2020-02", "t_invalid": "2020-04"},  # overlaps A
        {"id": "c", "label": "C", "t_valid": "2021-01", "t_invalid": "2021-02"},  # after both
        {"id": "d", "label": "D", "t_valid": None, "t_invalid": None},  # undated -> skipped
    ]
    rels = pairwise_relations(claims)
    kinds = {r["relation"] for r in rels}
    assert "overlaps" in kinds
    assert "before" not in kinds and "after" not in kinds  # trivial pairs omitted by default
    # D is undated, so it never appears.
    assert all("D" not in (r["a"], r["b"]) for r in rels)
    # With the flag, the trivial pairs come back.
    assert any(
        r["relation"] in ("before", "after")
        for r in pairwise_relations(claims, include_before_after=True)
    )


def test_engine_temporal_relations_on_temporal_fixture() -> None:
    r = build(TEMPORAL)
    res = QueryEngine(r.nodes, r.edges).temporal_relations()
    assert res["dated_claims"] >= 2
    # The May transfer's window ends exactly when the June correction begins -> "meets".
    assert any(rel["relation"] == "meets" for rel in res["relations"])


def test_engine_temporal_relations_scoped_to_entity() -> None:
    r = build(TEMPORAL)
    eng = QueryEngine(r.nodes, r.edges)
    scoped = eng.temporal_relations("Acme Corp")
    assert scoped["anchor"] == "Acme Corp"
    assert scoped["relations"]
