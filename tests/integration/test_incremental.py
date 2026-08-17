"""Phase 5: incremental rebuild (per-doc IE cache) + watch, byte-identical to full."""

import shutil
from pathlib import Path

from textgraph.core.incremental import DocIECache
from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes
from textgraph.pipeline import build
from textgraph.watch import corpus_signature, watch

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def _graph_bytes(result: object) -> bytes:
    r = result
    return dump_graph_bytes(
        build_graph_document(
            config_hash=r.config_hash,  # type: ignore[attr-defined]
            results=r.results,  # type: ignore[attr-defined]
            nodes=r.nodes,  # type: ignore[attr-defined]
            edges=r.edges,  # type: ignore[attr-defined]
        )
    )


def test_incremental_build_is_byte_identical_to_full(tmp_path: Path) -> None:
    full = _graph_bytes(build(DOCS))
    cache = tmp_path / "cache"
    cold = _graph_bytes(build(DOCS, cache_dir=cache))  # populates cache
    warm = _graph_bytes(build(DOCS, cache_dir=cache))  # reads cache
    assert cold == full
    assert warm == full


def test_cache_is_populated_and_reused(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    build(DOCS, cache_dir=cache_dir)
    n_files = len(list(cache_dir.glob("*.json")))
    assert n_files >= 3  # one per document

    # A fresh cache object over the same dir should report hits on rebuild.
    cache = DocIECache(cache_dir)
    build(DOCS, cache_dir=cache_dir)
    # The pipeline made its own cache object; assert the files still map 1:1 to docs.
    assert len(list(cache.dir.glob("*.json"))) == n_files


def test_incremental_stays_byte_identical_after_modify_and_delete(tmp_path: Path) -> None:
    # The G5 guarantee must hold for edits and removals, not just additions: an
    # incremental rebuild off a warm cache must byte-match a full build every time.
    work = tmp_path / "corpus"
    shutil.copytree(DOCS, work)
    cache = tmp_path / "cache"
    build(work, cache_dir=cache)  # warm the cache

    edited = sorted(work.glob("*.md"))[0]
    edited.write_text(
        edited.read_text(encoding="utf-8") + "\nEcho Ltd controls Foxtrot Inc.\n",
        encoding="utf-8",
    )
    assert _graph_bytes(build(work, cache_dir=cache)) == _graph_bytes(build(work))

    sorted(work.glob("*.md"))[-1].unlink()
    assert _graph_bytes(build(work, cache_dir=cache)) == _graph_bytes(build(work))


def test_editing_one_file_only_reextracts_it(tmp_path: Path) -> None:
    work = tmp_path / "corpus"
    shutil.copytree(DOCS, work)
    cache = tmp_path / "cache"
    build(work, cache_dir=cache)
    before = {p.name for p in cache.glob("*.json")}

    (work / "extra.md").write_text("# Extra\nDelta Trust controls Sigma Partners.\n")
    build(work, cache_dir=cache)
    after = {p.name for p in cache.glob("*.json")}
    # The original doc cache entries are untouched; exactly one new entry was added.
    assert before < after
    assert len(after - before) == 1


def test_watch_rebuilds_once_when_nothing_changes(tmp_path: Path) -> None:
    work = tmp_path / "corpus"
    shutil.copytree(DOCS, work)
    out = tmp_path / "out"
    builds: list[int] = []
    watch(
        work,
        out,
        interval=0,
        iterations=3,
        on_build=lambda r: builds.append(len(r.nodes)),
        sleep=lambda s: None,
    )
    assert len(builds) == 1  # unchanged corpus -> a single build across 3 cycles
    assert (out / "graph.json").exists()


def test_watch_on_diff_fires_with_the_change(tmp_path: Path) -> None:
    # The on_diff hook powers webhook/watchlist alerts: it must fire on a rebuild AFTER the
    # first, receiving the previous and current builds so a caller can diff them.
    from textgraph.l9_artifacts.diff import graph_diff

    work = tmp_path / "corpus"
    shutil.copytree(DOCS, work)
    out = tmp_path / "out"
    diffs: list[str] = []

    def _on_diff(prev: object, curr: object) -> None:
        d = graph_diff(prev.nodes, prev.edges, curr.nodes, curr.edges)  # type: ignore[attr-defined]
        diffs.append(d.summary())

    calls = {"n": 0}

    def _sleep(_s: float) -> None:
        # After the first cycle, add a document so the second cycle rebuilds and diffs.
        calls["n"] += 1
        if calls["n"] == 1:
            (work / "extra.md").write_text(
                "# New\nZeta Corp transferred $7,000 to Acme Corp.\n", encoding="utf-8"
            )

    watch(work, out, interval=0, iterations=3, on_diff=_on_diff, sleep=_sleep)
    assert diffs, "on_diff should fire once the corpus changes"
    assert diffs[0] != "no changes"  # the added document produced a real diff


def test_watch_signature_changes_on_edit(tmp_path: Path) -> None:
    work = tmp_path / "corpus"
    shutil.copytree(DOCS, work)
    sig1 = corpus_signature(work)
    (work / "new.md").write_text("# New\nOmega Bank controls Acme Corp.\n")
    assert corpus_signature(work) != sig1


def test_watch_rejects_output_inside_the_watched_dir(tmp_path: Path) -> None:
    import pytest

    work = tmp_path / "corpus"
    shutil.copytree(DOCS, work)
    # An output dir nested in the corpus would re-ingest its own artifacts forever.
    with pytest.raises(ValueError, match="outside the watched corpus"):
        watch(work, work / "out", iterations=1, sleep=lambda s: None)
