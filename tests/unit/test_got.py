"""Phase 10 tests: Graph-of-Thoughts data model + the complexity-gated reasoner."""

from pathlib import Path

from textgraph.got import GraphOfThoughts, Role, ThoughtGraph
from textgraph.got.reason import _dedup
from textgraph.l8_retrieval.model import Citation
from textgraph.pipeline import build

DOCS = Path(__file__).parent.parent / "fixtures" / "corpora" / "docs"
_CIT = Citation("doc:1", 0, 5, "h")


def _got() -> GraphOfThoughts:
    r = build(DOCS)
    return GraphOfThoughts(r.nodes, r.edges)


# -- data model -------------------------------------------------------------


def test_thought_grounded_requires_evidence_for_substantive_roles() -> None:
    g = ThoughtGraph()
    plan = g.add(Role.PLAN, "plan", "root")  # meta step: no evidence needed
    hyp_empty = g.add(Role.HYPOTHESIS, "guess", "aggregate")  # substantive, no evidence
    hyp_cited = g.add(Role.HYPOTHESIS, "claim", "aggregate", evidence=(_CIT,))
    assert plan.grounded
    assert not hyp_empty.grounded
    assert hyp_cited.grounded
    assert not g.fully_grounded  # the un-cited hypothesis fails the invariant


def test_thought_graph_ids_and_edges_are_deterministic() -> None:
    g = ThoughtGraph()
    a = g.add(Role.PLAN, "a", "root")
    b = g.add(Role.SUBPROBLEM, "b", "generate", parents=(a.id,), evidence=(_CIT,))
    assert (a.id, b.id) == ("t0", "t1")
    assert g.to_dict()["edges"] == [{"source": "t0", "target": "t1"}]


def test_dedup_orders_and_caps_citations() -> None:
    dup = [Citation("d", 10, 12, "h"), Citation("d", 1, 3, "h"), Citation("d", 10, 12, "h")]
    got = _dedup(dup)
    assert len(got) == 2  # de-duplicated
    assert [c.start for c in got] == [1, 10]  # stably ordered by (doc, start, end)


# -- reasoner ---------------------------------------------------------------


def test_simple_query_runs_a_cheap_grounded_linear_chain() -> None:
    res = _got().reason("who is John Doe", mode="adaptive")
    assert res.complexity == 1  # one named entity -> simple
    roles = [t.role for t in res.graph.thoughts]
    assert Role.PLAN in roles and Role.SUBPROBLEM in roles
    assert Role.VERIFICATION in roles and Role.SUMMARY in roles
    assert Role.HYPOTHESIS not in roles  # no aggregation for a single-entity query
    assert res.grounded and res.answer


def test_connection_query_aggregates_a_real_path_as_evidence() -> None:
    res = _got().reason("how is Acme Corp connected to Delta Trust", mode="adaptive")
    assert res.complexity >= 2
    operators = {t.operator for t in res.graph.thoughts}
    assert {"generate", "aggregate", "refine", "distill"} <= operators  # all four primitives
    hyp = next(t for t in res.graph.thoughts if t.role == Role.HYPOTHESIS)
    assert "Gamma Holdings" in hyp.content  # the real connecting path
    assert hyp.evidence  # bound to the path's citations
    assert res.grounded


def test_every_reasoning_step_cites_real_graph_spans() -> None:
    got = _got()
    for q in ("who controls Gamma Holdings", "how is Acme Corp connected to Delta Trust"):
        res = got.reason(q)
        assert res.graph.fully_grounded  # ESCARGOT invariant
        summary = next(t for t in res.graph.thoughts if t.role == Role.SUMMARY)
        assert summary.evidence


def test_adaptive_is_never_more_expensive_than_static() -> None:
    got = _got()
    queries = ["who is John Doe", "how is Acme Corp connected to Delta Trust", "which bank"]
    savings = 0
    for q in queries:
        a = got.reason(q, mode="adaptive")
        s = got.reason(q, mode="static")
        assert a.tool_calls <= s.tool_calls
        assert s.tool_calls <= got.max_tool_calls  # bounded (G7)
        savings += s.tool_calls - a.tool_calls
    assert savings > 0  # strictly cheaper overall


def test_reasoning_is_deterministic() -> None:
    got = _got()
    assert (
        got.reason("how is Acme Corp connected to Delta Trust").to_dict()
        == got.reason("how is Acme Corp connected to Delta Trust").to_dict()
    )


def test_query_with_no_named_entity_returns_grounded_empty() -> None:
    res = _got().reason("zzz nonexistent qqq")
    assert res.complexity == 0
    assert res.grounded  # vacuously: only a Plan, no unsupported claims
    assert "No graph evidence" in res.answer


def test_injected_engine_honours_access_control_on_the_reason_path() -> None:
    # Phase 0 fix: when a policy-bearing QueryEngine is injected, reason() must reuse it (not
    # build its own), so restricted content never leaks through Graph-of-Thoughts.
    from textgraph.l8_retrieval.engine import QueryEngine
    from textgraph.security import RebacStore, RelationTuple, SecurityContext, SecurityPolicy

    secure = Path(__file__).parent.parent / "fixtures" / "corpora" / "secure"
    r = build(secure)
    plain = QueryEngine(r.nodes, r.edges)
    public_doc = sorted(plain._node_docs[plain.resolve("Gamma Holdings")])[0]
    policy = SecurityPolicy(
        rebac=RebacStore([RelationTuple(f"doc:{public_doc}", "viewer", "user:alice")])
    )
    engine = QueryEngine(r.nodes, r.edges, policy=policy)
    got = GraphOfThoughts(engine=engine)
    assert got.engine is engine  # reused, not rebuilt (no per-call re-index, honours policy)
    ctx = SecurityContext("alice")
    # Under alice's context every thought must be about authorised content only: the secret
    # entities (Shadow LLC / Phantom Bank) must never appear in any thought's text.
    res = got.reason("how is Acme Corp connected to Shadow LLC and Phantom Bank", context=ctx)
    assert res.grounded
    blob = " ".join(t.content for t in res.graph.thoughts) + res.answer
    assert "Shadow" not in blob and "Phantom" not in blob  # no context-bleed via reason()
    # Control: with no context the injected engine is unrestricted and the secret surfaces.
    leak = GraphOfThoughts(engine=QueryEngine(r.nodes, r.edges)).reason("Shadow LLC Phantom Bank")
    assert "Shadow" in " ".join(t.content for t in leak.graph.thoughts) + leak.answer


def test_entity_less_but_answerable_query_anchors_on_search() -> None:
    # A question that names no entity but that search can answer must still produce a
    # grounded chain (anchored on the top hit), not "no evidence" — complexity stays 0,
    # so it runs the cheap linear chain rather than the expensive branched one.
    res = _got().reason("who transferred funds to whom")
    assert res.complexity == 0
    assert res.grounded
    assert "No graph evidence" not in res.answer
    assert res.graph.thoughts[-1].role == Role.SUMMARY
    assert res.graph.thoughts[-1].evidence  # the summary cites real spans
