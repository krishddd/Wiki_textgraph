"""L4 optional LLM pass: GENERATED summaries, caching, budget, graceful skip.

All tests use a mock client — no network — so the opt-in layer is fully covered in CI
without a live endpoint.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest
from textgraph.core.config import Config
from textgraph.l4_llm_optional import PromptCache, resolve_client, synthesize
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


@dataclass
class MockClient:
    model: str = "mock-model"
    temperature: float = 0.0
    max_tokens: int = 256
    reply: str = "A concise, grounded summary of the cluster."
    calls: int = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.reply


def _analytics_build() -> object:
    return build(DOCS)


def test_resolve_client_returns_none_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("TEXTGRAPH_LLM_API_KEY", "API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert resolve_client(Config(llm_enabled=True)) is None


def test_resolve_client_builds_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("MODEL_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    client = resolve_client(Config(llm_enabled=True))
    assert client is not None
    assert client.model == "test-model"
    assert client.api_key == "secret"


def test_synthesize_emits_generated_summaries(tmp_path: Path) -> None:
    r = _analytics_build()
    client = MockClient()
    gen_nodes, gen_edges = synthesize(
        r.nodes,
        r.edges,
        r.analytics,
        client,
        PromptCache(tmp_path),
        max_calls=8,  # type: ignore[attr-defined]
    )
    assert gen_nodes
    for n in gen_nodes:
        assert n.labels == ("Summary",)
        assert n.properties["tag"] == "GENERATED"
        assert n.properties["text"]
    # SUMMARIZES edges are GENERATED and carry no source spans (exempt from provenance).
    assert gen_edges
    for e in gen_edges:
        assert e.predicate == "SUMMARIZES"
        assert str(e.tag) == "GENERATED"
        assert e.source_spans == ()


def test_responses_are_cached(tmp_path: Path) -> None:
    r = _analytics_build()
    cache = PromptCache(tmp_path)
    client = MockClient()
    synthesize(r.nodes, r.edges, r.analytics, client, cache, max_calls=8)  # type: ignore[attr-defined]
    first_calls = client.calls
    assert first_calls >= 1
    # Second run over the same cache should make no new client calls.
    synthesize(r.nodes, r.edges, r.analytics, client, cache, max_calls=8)  # type: ignore[attr-defined]
    assert client.calls == first_calls
    assert cache.hits >= first_calls


def test_budget_caps_calls(tmp_path: Path) -> None:
    r = _analytics_build()
    client = MockClient()
    synthesize(r.nodes, r.edges, r.analytics, client, PromptCache(tmp_path), max_calls=1)  # type: ignore[attr-defined]
    assert client.calls <= 1


def test_pipeline_llm_enabled_but_unconfigured_skips_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("TEXTGRAPH_LLM_API_KEY", "API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    result = build(DOCS, config=Config(llm_enabled=True))
    assert result.graph_stats.get("summaries", 0) == 0
    assert not [n for n in result.nodes if "Summary" in n.labels]


def test_pipeline_llm_enabled_with_mock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import textgraph.l4_llm_optional as l4

    monkeypatch.setattr(l4, "resolve_client", lambda config: MockClient())
    result = build(DOCS, config=Config(llm_enabled=True))
    assert result.graph_stats["summaries"] >= 1
    summaries = [n for n in result.nodes if "Summary" in n.labels]
    assert summaries and summaries[0].properties["tag"] == "GENERATED"
