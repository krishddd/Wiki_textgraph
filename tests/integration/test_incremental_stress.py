"""Sprint 4.2: incremental reindex under deletes/updates + partial-write recovery (G5).

The invariant: an incremental rebuild is **byte-identical** to a clean full rebuild of the
same corpus, no matter what changed (add / modify / delete), and a corrupt or partially
written cache entry never fails a build — it is transparently re-extracted.
"""

from pathlib import Path

from textgraph.core.incremental import DocIECache
from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes
from textgraph.pipeline import build


def _graph_bytes(root: Path, cache: Path | None = None) -> bytes:
    r = build(root, cache_dir=cache)
    doc = build_graph_document(
        config_hash=r.config_hash, results=r.results, nodes=r.nodes, edges=r.edges
    )
    return dump_graph_bytes(doc)


def test_incremental_delete_matches_clean_rebuild(tmp_path: Path) -> None:
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_bytes(b"Acme Corp controls Gamma Holdings.\n")
    (corpus / "b.md").write_bytes(b"Zeta Corp wired funds to Omega Bank.\n")
    cache = tmp_path / "cache"

    build(corpus, cache_dir=cache)  # warm the cache with both docs
    (corpus / "b.md").unlink()  # delete one document
    incremental = _graph_bytes(corpus, cache)

    # A clean build of just the surviving corpus must be byte-identical.
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    (clean_dir / "a.md").write_bytes(b"Acme Corp controls Gamma Holdings.\n")
    assert incremental == _graph_bytes(clean_dir)
    assert b"Zeta Corp" not in incremental  # the deleted doc's content is gone


def test_incremental_update_matches_clean_rebuild(tmp_path: Path) -> None:
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_bytes(b"Acme Corp controls Gamma Holdings.\n")
    cache = tmp_path / "cache"

    build(corpus, cache_dir=cache)  # warm
    (corpus / "a.md").write_bytes(b"Acme Corp controls Delta Trust.\n")  # modify in place
    incremental = _graph_bytes(corpus, cache)

    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    (clean_dir / "a.md").write_bytes(b"Acme Corp controls Delta Trust.\n")
    assert incremental == _graph_bytes(clean_dir)
    assert b"Delta Trust" in incremental


def test_corrupt_cache_entry_is_recovered(tmp_path: Path) -> None:
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_bytes(b"Acme Corp controls Gamma Holdings.\n")
    cache = tmp_path / "cache"

    good = _graph_bytes(corpus, cache)  # warm + baseline
    # Simulate a crash mid-write: truncate every cache entry to invalid JSON.
    poisoned = list(cache.glob("*.json"))
    assert poisoned, "cache should have entries after a warm build"
    for f in poisoned:
        f.write_text('{"nodes": [trunc', encoding="utf-8")

    # The build must not fail — corrupt entries are treated as misses and re-extracted,
    # producing the identical graph (G5 robustness).
    recovered = _graph_bytes(corpus, cache)
    assert recovered == good


def test_cache_get_treats_corrupt_entry_as_miss(tmp_path: Path) -> None:
    cache = DocIECache(tmp_path / "cache")
    p = cache._path("blake3:deadbeef", "cfg123456789")
    p.write_text("not json at all {", encoding="utf-8")
    assert cache.get("blake3:deadbeef", "cfg123456789") is None
    assert not p.exists()  # the poisoned entry is dropped
    assert cache.misses == 1
