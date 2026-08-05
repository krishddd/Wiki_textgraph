"""Phase 8: MaxSim late-interaction operator, hash embedder, page retrieval."""

from pathlib import Path

from textgraph.core.config import Config
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l8_retrieval import QueryEngine
from textgraph.l8_retrieval.vision import HashEmbedder, VisionPage, VisionRetriever, maxsim
from textgraph.l8_retrieval.vision.embed import _colpali_embedder, resolve_embedder
from textgraph.l8_retrieval.vision.maxsim import normalize
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


def test_maxsim_math_and_edges() -> None:
    a = normalize((1.0, 0.0))
    b = normalize((0.0, 1.0))
    # Query [a, b] vs page [a]: a matches a (1.0), b's best is a (0.0) -> 1.0 total.
    assert abs(maxsim((a, b), (a,)) - 1.0) < 1e-9
    assert abs(maxsim((a, b), (a, b)) - 2.0) < 1e-9  # both align perfectly
    assert maxsim((), (a,)) == 0.0 and maxsim((a,), ()) == 0.0


def test_hash_embedder_is_deterministic_and_normalised() -> None:
    e = HashEmbedder(dim=32)
    v1 = e.embed("acme transferred funds")
    v2 = e.embed("acme transferred funds")
    assert v1 == v2  # deterministic
    assert len(v1) == 3  # one vector per token
    for vec in v1:
        assert abs(sum(x * x for x in vec) ** 0.5 - 1.0) < 1e-9  # unit length


def test_maxsim_ranks_related_text_above_unrelated() -> None:
    e = HashEmbedder()
    q = e.embed("acme transferred funds to beta")
    related = e.embed("acme corp transferred funds to beta ltd")
    unrelated = e.embed("the weather today is sunny and warm")
    assert maxsim(q, related) > maxsim(q, unrelated)


def test_vision_retriever_returns_cited_bounded_pages() -> None:
    pages = [
        VisionPage("page:1", "d1", "acme transfers", "Acme Corp wired funds to Beta Ltd."),
        VisionPage("page:2", "d2", "weather", "It is sunny with light winds today."),
    ]
    hits = VisionRetriever(pages).search("who transferred funds", k=2)
    assert hits
    assert hits[0].node_id == "page:1"  # the money page wins
    assert hits[0].kind == "page"


def test_engine_vision_search_over_the_graph() -> None:
    r = build(DOCS)
    qe = QueryEngine(r.nodes, r.edges)
    res = qe.vision_search("who transferred funds to whom", k=3)
    assert res.routing == "vision"
    assert res.hits
    assert all(h.kind == "page" for h in res.hits)
    # Deterministic.
    assert qe.vision_search("funds").to_dict() == qe.vision_search("funds").to_dict()


def test_resolve_embedder_falls_back_without_vision_extra() -> None:
    # [vision] isn't installed in CI, so 'colpali' must degrade to the hash embedder.
    got = resolve_embedder(Config(vision_backend="colpali"))
    assert isinstance(got, HashEmbedder)
    assert isinstance(resolve_embedder(Config()), HashEmbedder)


def test_colpali_embedder_raises_unsupported_without_extra() -> None:
    try:
        import colpali_engine  # noqa: F401
    except ImportError:
        import pytest

        with pytest.raises(UnsupportedFormat, match="vision"):
            _colpali_embedder(Config(vision_backend="colpali"))
