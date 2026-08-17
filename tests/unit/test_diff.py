"""Graph diff primitive + watch alerts."""

from pathlib import Path

from textgraph.alerts import build_payload, post_webhook
from textgraph.l9_artifacts.diff import GraphDiff, graph_diff
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _build_text(tmp_path: Path, name: str, text: str):
    d = tmp_path / name
    d.mkdir()
    (d / "case.md").write_text(text, encoding="utf-8")
    return build(d)


def test_self_diff_is_empty() -> None:
    # Content-addressed identity: a build diffed against itself has no changes.
    r = build(DOCS)
    d = graph_diff(r.nodes, r.edges, r.nodes, r.edges)
    assert d.is_empty
    assert d.summary() == "no changes"


def test_added_entity_and_relation_are_detected(tmp_path: Path) -> None:
    before = _build_text(tmp_path, "a", "# Case\nAcme Corp controls Beta Ltd.\n")
    after = _build_text(
        tmp_path,
        "b",
        "# Case\nAcme Corp controls Beta Ltd.\nOmega Bank transferred $9,000 to Acme Corp.\n",
    )
    d = graph_diff(before.nodes, before.edges, after.nodes, after.edges)
    assert not d.is_empty
    assert "Omega Bank" in d.added_entities
    preds = {(r["source"], r["predicate"], r["target"]) for r in d.added_relations}
    assert ("Omega Bank", "TRANSFERRED", "Acme Corp") in preds
    # Direction matters: the reverse build removes them.
    d2 = graph_diff(after.nodes, after.edges, before.nodes, before.edges)
    assert "Omega Bank" in d2.removed_entities


def test_new_contradiction_is_surfaced(tmp_path: Path) -> None:
    before = _build_text(
        tmp_path, "a", "# Filing\nOn 2026-05-01, Acme Corp transferred $1,000,000 to Beta Ltd.\n"
    )
    after = _build_text(
        tmp_path,
        "b",
        "# Filing\nOn 2026-05-01, Acme Corp transferred $1,000,000 to Beta Ltd.\n"
        "On 2026-06-01, Acme Corp did not transfer $1,000,000 to Beta Ltd.\n",
    )
    d = graph_diff(before.nodes, before.edges, after.nodes, after.edges)
    assert d.added_contradictions, "the dated negation should register as a new contradiction"
    assert "new contradiction" in d.summary()


def test_watchlist_restricts_the_diff(tmp_path: Path) -> None:
    before = _build_text(tmp_path, "a", "# Case\nAcme Corp controls Beta Ltd.\n")
    after = _build_text(
        tmp_path,
        "b",
        "# Case\nAcme Corp controls Beta Ltd.\nGamma Inc transferred $5,000 to Delta LLC.\n",
    )
    # The change is entirely about Gamma/Delta; a watchlist of Acme sees nothing.
    d = graph_diff(before.nodes, before.edges, after.nodes, after.edges, entities={"Acme Corp"})
    assert d.is_empty
    # A watchlist including Gamma sees it.
    d2 = graph_diff(before.nodes, before.edges, after.nodes, after.edges, entities={"Gamma Inc"})
    assert not d2.is_empty


def test_community_ids_renumbering_does_not_create_false_moves() -> None:
    # Communities are renumbered per build, so a self-diff must report ZERO moves — proving
    # membership (not id) is what's compared.
    r = build(DOCS)
    d = graph_diff(r.nodes, r.edges, r.nodes, r.edges)
    assert d.community_moves == []


def test_to_dict_and_counts_roundtrip() -> None:
    d = GraphDiff(
        added_entities=["X"], added_relations=[{"source": "X", "predicate": "P", "target": "Y"}]
    )
    payload = d.to_dict()
    assert payload["counts"]["added_entities"] == 1
    assert payload["counts"]["added_relations"] == 1
    assert "no changes" not in d.summary()


# -- alerts -------------------------------------------------------------------------------


def test_build_payload_is_slack_compatible() -> None:
    d = GraphDiff(added_entities=["Acme"])
    payload = build_payload(d, source="case-files")
    assert "text" in payload  # Slack/Teams render `text`
    assert payload["text"].startswith("TextGraph:")
    assert "case-files" in payload["text"]
    assert payload["diff"]["counts"]["added_entities"] == 1


def test_post_webhook_reports_success_and_failure_without_network() -> None:
    d = GraphDiff(added_entities=["Acme"])
    payload = build_payload(d)

    class _Resp:
        status = 200

    captured = {}

    def _ok(req, timeout):
        captured["url"] = req.full_url
        return _Resp()

    assert post_webhook("http://example/hook", payload, opener=_ok) is True
    assert captured["url"] == "http://example/hook"

    def _boom(req, timeout):
        raise OSError("connection refused")

    # A failing endpoint returns False, never raises — the watcher must survive it.
    assert post_webhook("http://example/hook", payload, opener=_boom) is False
