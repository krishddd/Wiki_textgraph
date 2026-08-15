"""LLM augmentation — relation extraction (input) + answer synthesis (output).

Uses a stub client so the logic (JSON parsing, GENERATED tagging, provenance, caching,
grounding) is tested deterministically with no network — the live endpoint is exercised
separately.
"""

from pathlib import Path

import pytest
from textgraph.core.config import Config
from textgraph.l4_llm_optional.cache import PromptCache
from textgraph.l4_llm_optional.extract import _parse_triples, extract_llm_relations
from textgraph.l8_retrieval.model import Citation
from textgraph.l8_retrieval.narrate import narrate
from textgraph.pipeline import build
from textgraph.store.base import SourceSpan

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"


class _StubClient:
    """Duck-typed LLMClient: returns a canned completion and counts calls."""

    model = "stub-model"

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self._response


# --- triple parsing ----------------------------------------------------------


def test_parse_triples_plain_array() -> None:
    raw = '[{"subject":"A","predicate":"regulates","object":"B"}]'
    assert _parse_triples(raw) == [("A", "REGULATES", "B")]


def test_parse_triples_fenced_and_noisy() -> None:
    raw = 'Here you go:\n```json\n[{"subject":"X","predicate":"amends the","object":"Y"}]\n```'
    assert _parse_triples(raw) == [("X", "AMENDS_THE", "Y")]


def test_parse_triples_invalid_returns_empty() -> None:
    assert _parse_triples("no json here") == []
    assert _parse_triples('[{"subject":"only"}]') == []  # missing predicate/object


# --- extraction (input) ------------------------------------------------------


def _span() -> SourceSpan:
    return SourceSpan(doc_id="d1", start=0, end=10, hash="h")


def test_extract_emits_generated_nodes_and_edges(tmp_path: Path) -> None:
    client = _StubClient('[{"subject":"Commission","predicate":"designates","object":"Body"}]')
    cache = PromptCache(tmp_path)
    chunks = [("chunk:1", "The Commission designates the notified Body for conformity.", _span())]
    nodes, edges = extract_llm_relations(chunks, client, cache)
    assert len(edges) == 1
    e = edges[0]
    assert str(e.tag) == "GENERATED"  # quarantined
    assert e.predicate == "DESIGNATES"
    assert e.source_spans and e.source_spans[0].doc_id == "d1"  # cited to the chunk
    assert {n.properties["name"] for n in nodes} == {"Commission", "Body"}
    assert all(n.properties.get("source") == "llm" for n in nodes)


def test_extract_is_cached(tmp_path: Path) -> None:
    client = _StubClient('[{"subject":"A","predicate":"x","object":"B"}]')
    cache = PromptCache(tmp_path)
    chunks = [("chunk:1", "A x B and more text to pass the length floor here.", _span())]
    extract_llm_relations(chunks, client, cache)
    assert client.calls == 1
    # A fresh client + the same on-disk cache -> zero new calls.
    client2 = _StubClient("[]")
    extract_llm_relations(chunks, client2, PromptCache(tmp_path))
    assert client2.calls == 0


def test_extract_merges_onto_existing_entity(tmp_path: Path) -> None:
    # A triple endpoint whose normalized name matches an entity the deterministic pipeline
    # already produced must REUSE that id (no parallel `entity:LLM:` dot) — the fix for the
    # duplicate-node sparsity. "Acme Corp" is known; "Beta Ltd" is new.
    client = _StubClient('[{"subject":"Acme Corp","predicate":"pays","object":"Beta Ltd"}]')
    cache = PromptCache(tmp_path)
    chunks = [("chunk:1", "Acme Corp pays Beta Ltd a large sum every quarter here.", _span())]
    existing = {"acme corp": "entity:Organization:acme corp"}
    nodes, edges = extract_llm_relations(chunks, client, cache, existing_entities=existing)
    assert len(edges) == 1
    e = edges[0]
    assert e.subject == "entity:Organization:acme corp"  # merged onto the deterministic node
    assert e.object.startswith("entity:LLM:")  # the unknown endpoint is a fresh LLM node
    # The known entity is NOT re-emitted as a duplicate node.
    assert all(n.node_id != "entity:Organization:acme corp" for n in nodes)


def test_extract_drops_self_loop_after_merge(tmp_path: Path) -> None:
    # If both endpoints resolve to the same node, the edge carries no information.
    client = _StubClient('[{"subject":"Acme","predicate":"is","object":"Acme Corp"}]')
    existing = {"acme": "entity:Organization:acme", "acme corp": "entity:Organization:acme"}
    _nodes, edges = extract_llm_relations(
        [("chunk:1", "Acme is Acme Corp, the same firm, mentioned twice here.", _span())],
        client,
        PromptCache(tmp_path),
        existing_entities=existing,
    )
    assert edges == []


def test_extract_respects_call_budget(tmp_path: Path) -> None:
    client = _StubClient('[{"subject":"A","predicate":"x","object":"B"}]')
    chunks = [
        (f"chunk:{i}", f"Sentence number {i} with enough length to be extracted here.", _span())
        for i in range(5)
    ]
    extract_llm_relations(chunks, client, PromptCache(tmp_path), max_calls=2)
    assert client.calls == 2  # stopped at the budget


def test_llm_extract_off_by_default() -> None:
    r = build(DOCS)
    assert r.graph_stats.get("llm_relations", 0) == 0
    assert all(str(e.tag) != "GENERATED" for e in r.edges)  # no GENERATED edges by default


class _TripleClient:
    """Stub whose completion parses as one extraction triple (and doubles as summary text)."""

    model = "stub-model"
    temperature = 0.0
    max_tokens = 256

    def complete(self, system: str, user: str) -> str:
        return '[{"subject":"Alpha","predicate":"relates to","object":"Beta"}]'


def test_llm_extract_count_matches_generated_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    # The reported `llm_relations` must equal the GENERATED edges added — no hidden summary
    # edges inflating the graph (the count-bug fix): --llm-extract does extraction ONLY.
    import textgraph.l4_llm_optional as l4

    monkeypatch.setattr(l4, "resolve_client", lambda config: _TripleClient())
    r = build(DOCS, config=Config(llm_extract=True))  # llm_enabled defaults False
    generated = [e for e in r.edges if str(e.tag) == "GENERATED"]
    assert r.graph_stats["llm_relations"] == len(generated) > 0  # count is exact
    assert r.graph_stats.get("summaries", 0) == 0  # extraction did NOT trigger summaries
    assert not [n for n in r.nodes if "Summary" in n.labels]
    assert all(e.properties.get("source") == "llm" for e in generated)


def test_llm_entities_are_ranked_clustered_and_laid_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE regression guard for the "floating dots" bug: because extraction now runs BEFORE
    # analytics/layout, every LLM-contributed entity must leave the pipeline positioned,
    # ranked, and in a real community. A node at pagerank==0 / community==-1 / no position
    # would mean the pass slipped back after L7 — exactly the class of bug this release fixes.
    import textgraph.l4_llm_optional as l4

    monkeypatch.setattr(l4, "resolve_client", lambda config: _TripleClient())
    r = build(DOCS, config=Config(llm_extract=True))
    llm_nodes = [n for n in r.nodes if n.properties.get("source") == "llm"]
    assert llm_nodes, "the stub should have produced at least one new LLM entity"
    for n in llm_nodes:
        assert "x" in n.properties and "y" in n.properties  # laid out
        assert int(n.properties.get("community", -1)) >= 0  # clustered
        assert "pagerank" in n.properties  # ranked
    # And no LLM node carries the old provenance-as-type stamp.
    assert all(n.properties.get("etype") != "LLM" for n in r.nodes)


def test_summaries_are_decoupled_from_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    import textgraph.l4_llm_optional as l4

    monkeypatch.setattr(l4, "resolve_client", lambda config: _TripleClient())
    r = build(DOCS, config=Config(llm_enabled=True))  # summaries switch only
    assert r.graph_stats["summaries"] >= 1
    assert r.graph_stats.get("llm_relations", 0) == 0  # extraction did NOT run


# --- synthesis (output) ------------------------------------------------------


def test_narrate_grounds_on_passages() -> None:
    client = _StubClient("The purpose is to regulate AI [1].")
    passages = [("AI systems must be safe.", [Citation("d1", 0, 5, "h")])]
    ans = narrate(client, "what is the purpose", passages)
    assert ans is not None
    assert ans.tag == "GENERATED"
    assert "[1]" in ans.text
    assert ans.citations == [Citation("d1", 0, 5, "h")]


def test_narrate_no_evidence_returns_none() -> None:
    client = _StubClient("should not be called")
    assert narrate(client, "q", []) is None
    assert narrate(client, "q", [("   ", [])]) is None  # blank snippets -> nothing to ground
    assert client.calls == 0


def test_default_model_is_nemotron() -> None:
    from textgraph.l4_llm_optional.client import DEFAULT_LLM_MODEL

    assert "Nemotron" in DEFAULT_LLM_MODEL  # the pipeline's default LLM when env is unset
