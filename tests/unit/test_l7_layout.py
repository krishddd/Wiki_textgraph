"""L7 force-directed layout: deterministic, framed, folded into the graph."""

from pathlib import Path

from textgraph.l7_analytics.algorithms import build_adjacency
from textgraph.l7_analytics.layout import force_layout
from textgraph.pipeline import build, build_graph_bytes

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _triangle_adj() -> dict[str, list[tuple[str, float]]]:
    return build_adjacency(
        ["a", "b", "c", "d"],
        [("a", "b", 1.0), ("b", "c", 1.0), ("c", "a", 1.0), ("a", "d", 1.0)],
    )


def test_layout_is_deterministic_and_order_independent() -> None:
    adj = _triangle_adj()
    comm = {"a": 0, "b": 0, "c": 0, "d": 1}
    a = force_layout(["a", "b", "c", "d"], adj, community_of=comm)
    b = force_layout(["d", "c", "b", "a"], adj, community_of=comm)  # shuffled input
    assert a == b


def test_layout_stays_in_frame_and_handles_degenerate_inputs() -> None:
    pos = force_layout(["a", "b", "c", "d"], _triangle_adj())
    assert all(-500.0 <= x <= 500.0 and -500.0 <= y <= 500.0 for x, y in pos.values())
    assert force_layout([], {}) == {}
    assert force_layout(["solo"], {}) == {"solo": (0.0, 0.0)}


def test_coordinates_are_baked_onto_entities_and_stay_byte_identical() -> None:
    result = build(DOCS)
    entities = [n for n in result.nodes if "Entity" in n.labels]
    assert entities
    for n in entities:
        assert "x" in n.properties and "y" in n.properties
    # Layout must not break the determinism gate.
    assert build_graph_bytes(DOCS) == build_graph_bytes(DOCS)
