"""Analyst loop: resolution hints, annotation sidecar, LLM cache status."""

import json
from pathlib import Path

from textgraph.console.annotations import AnnotationStore
from textgraph.l4_llm_optional.cache import cache_stats
from textgraph.l6_graph_model.resolution import ResolutionHint, resolution_hint
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

TEMPORAL = Path(__file__).parent.parent / "fixtures" / "corpora" / "temporal"


class _C:
    """A minimal claim stand-in for the resolution rule ladder."""

    def __init__(self, subject, predicate, obj, *, polarity="pos", confidence=0.5, t_valid=None):
        self.claim_id = f"{subject}|{predicate}|{obj}|{polarity}"
        self.subject, self.predicate, self.object = subject, predicate, obj
        self.polarity, self.confidence = polarity, confidence
        self.t_valid, self.t_invalid = t_valid, None


# -- resolution hints ---------------------------------------------------------------------


def test_recency_wins_dated_correction() -> None:
    a = _C("Acme", "TRANSFERRED", "Beta", t_valid="2026-05-01")
    b = _C("Acme", "TRANSFERRED", "Beta", polarity="neg", t_valid="2026-06-01")
    hint = resolution_hint(a, b)
    assert hint.recommend == "b"  # the June correction supersedes the May assertion
    assert hint.basis == "recency"
    assert "2026-06-01" in hint.reason


def test_confidence_breaks_undated_tie() -> None:
    a = _C("Acme", "CONTROLS", "Beta", confidence=0.9)
    b = _C("Acme", "CONTROLS", "Beta", polarity="neg", confidence=0.4)
    hint = resolution_hint(a, b)
    assert hint.recommend == "a"
    assert hint.basis == "confidence"


def test_no_basis_flags_manual_review() -> None:
    a = _C("Acme", "CONTROLS", "Beta", confidence=0.6)
    b = _C("Acme", "CONTROLS", "Beta", polarity="neg", confidence=0.6)
    hint = resolution_hint(a, b)
    assert hint.recommend is None
    assert hint.basis == "none"
    assert isinstance(hint, ResolutionHint)


def test_engine_resolution_hints_on_temporal_fixture() -> None:
    r = build(TEMPORAL)
    hints = QueryEngine(r.nodes, r.edges).resolution_hints()
    assert hints, "temporal fixture has a dated correction -> a contradiction with a hint"
    h = hints[0]
    assert h["hint"]["recommend"] in ("a", "b")
    assert h["hint"]["basis"] == "recency"  # the dated negation supersedes


# -- annotation sidecar -------------------------------------------------------------------


def test_annotation_store_in_memory_roundtrip() -> None:
    store = AnnotationStore(None)
    store.set("entity:acme", status="confirmed", note="verified via filing")
    assert store.all()["entity:acme"] == {"status": "confirmed", "note": "verified via filing"}
    # An empty annotation removes the entry.
    store.set("entity:acme", status="none", note="")
    assert "entity:acme" not in store.all()


def test_annotation_store_persists_to_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "annotations.json"
    store = AnnotationStore(sidecar)
    store.set("entity:beta", status="disputed", note="conflicting dates")
    assert sidecar.is_file()
    # A fresh store loads the persisted state.
    reloaded = AnnotationStore(sidecar)
    assert reloaded.all()["entity:beta"]["status"] == "disputed"
    # graph.json is never touched — the sidecar is the only artifact written.
    assert json.loads(sidecar.read_text())["entity:beta"]["note"] == "conflicting dates"


def test_annotation_store_rejects_unknown_status() -> None:
    store = AnnotationStore(None)
    stored = store.set("n", status="bogus", note="x")
    assert stored["status"] == "none"  # unknown status is normalised, not stored raw


def test_annotation_store_survives_corrupt_sidecar(tmp_path: Path) -> None:
    sidecar = tmp_path / "a.json"
    sidecar.write_text("{ not json", encoding="utf-8")
    store = AnnotationStore(sidecar)  # must not raise
    assert store.all() == {}


# -- cache status -------------------------------------------------------------------------


def test_cache_stats_cold_on_a_non_cache_dir(tmp_path: Path) -> None:
    # A build-output dir full of graph.json/manifest.json must read COLD, not warm.
    (tmp_path / "graph.json").write_text('{"nodes":[]}', encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    stats = cache_stats(tmp_path)
    assert stats["warm"] is False
    assert stats["entries"] == 0


def test_cache_stats_warm_on_a_real_cache(tmp_path: Path) -> None:
    cache = tmp_path / "llm"
    cache.mkdir()
    (cache / ("a" * 64 + ".json")).write_text('{"response":"hello"}', encoding="utf-8")
    stats = cache_stats(tmp_path)  # given the parent; finds llm/ beneath
    assert stats["warm"] is True
    assert stats["entries"] == 1
    assert stats["bytes"] > 0
