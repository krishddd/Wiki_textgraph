"""Dense-embedding retrieval — fusion, cache, and the deterministic hash backend."""

from pathlib import Path

from textgraph.core.config import Config
from textgraph.l8_retrieval import QueryEngine
from textgraph.l8_retrieval.dense import (
    CachedEmbedder,
    HashTextEmbedder,
    cosine,
    resolve_text_embedder,
)
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_cosine_basics() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector -> 0, no crash


def test_resolve_off_by_default() -> None:
    assert resolve_text_embedder(Config()) is None  # embed_backend "" -> disabled


def test_hash_embedder_is_deterministic() -> None:
    e = HashTextEmbedder(dim=64)
    a = e.embed_batch(["high risk ai systems"])
    b = e.embed_batch(["high risk ai systems"])
    assert a == b and len(a[0]) == 64


def test_cache_only_embeds_misses(tmp_path: Path) -> None:
    cfg = Config(embed_backend="hash", embed_dim=32)
    e1 = resolve_text_embedder(cfg, cache_dir=tmp_path)
    assert isinstance(e1, CachedEmbedder)
    v1 = e1.embed_batch(["a", "b", "c"])
    # A fresh instance loads the persisted cache from disk and returns identical vectors.
    e2 = resolve_text_embedder(cfg, cache_dir=tmp_path)
    v2 = e2.embed_batch(["a", "b", "c"])
    assert v1 == v2
    assert list(tmp_path.glob("embed-*.json"))  # cache persisted


def test_dense_index_built_and_fused() -> None:
    r = build(DOCS)
    emb = resolve_text_embedder(Config(embed_backend="hash", embed_dim=64))
    eng = QueryEngine(r.nodes, r.edges, text_embedder=emb)
    # Every chunk got a vector of the embedder's dimension.
    n_chunks = sum(1 for n in r.nodes if "Chunk" in n.labels)
    assert len(eng._dense) == n_chunks and n_chunks > 0
    # Search still returns cited hits with the dense signal fused in.
    res = eng.search("who transferred money", k=5).to_dict()
    assert res["hits"]
    assert any(h["citations"] for h in res["hits"])


def test_dense_absent_engine_matches_default() -> None:
    # With no embedder the engine behaves exactly as before (no dense index).
    r = build(DOCS)
    eng = QueryEngine(r.nodes, r.edges)
    assert eng._dense == {}
    assert eng.search("Acme", k=3).to_dict()["hits"]


def test_graph_content_unaffected_by_embed_config() -> None:
    # Dense retrieval is query-time only: embed_* settings must not change graph content
    # (only config_hash reflects them, like the vision fields).
    import json

    from textgraph.pipeline import build_graph_bytes

    a = json.loads(build_graph_bytes(DOCS))
    b = json.loads(build_graph_bytes(DOCS, config=Config(embed_backend="hash", embed_dim=128)))
    assert a["nodes"] == b["nodes"]
    assert a["edges"] == b["edges"]
