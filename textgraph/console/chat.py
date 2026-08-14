"""The "Ask" chat backend — a grounded, deterministic answer over the graph (Phase A).

A natural-language question is *routed* to the right graph tool (reason / search / path /
why / neighbors / timeline / contradictions / communities / stats / gql) and answered with a
templated, **cited** :class:`ChatAnswer` that both replies in the chat and tells the
frontend which nodes and edges to highlight. There is **no LLM**: the answer text is filled
straight from the cited tool result, so the whole feature is deterministic and works
offline (G1/G2). Every factual line carries the tool's ``[doc:span]`` citations (G3).

Multi-turn is stateless on the server: the client sends the previous answer's primary
entity as ``focus``, and follow-ups ("why?", "who controls it?") resolve their missing
entity against it. The reasoner is built once per engine and reused (no per-message
re-index), and inherits the engine's access-control posture on every call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textgraph.got.reason import GraphOfThoughts
from textgraph.gql.engine import GQLEngine
from textgraph.gql.errors import GQLError
from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.l8_retrieval.grounding import ABSTENTION_TEXT, assess
from textgraph.l8_retrieval.model import Citation
from textgraph.l8_retrieval.routing import TOOLS, classify_query

# One reasoner per engine (identity-keyed); the console builds its engine once, so this
# avoids rebuilding BM25/PPR indexes on every message.
_REASONERS: dict[int, GraphOfThoughts] = {}


def _reasoner_for(engine: QueryEngine) -> GraphOfThoughts:
    got = _REASONERS.get(id(engine))
    if got is None:
        gql = GQLEngine(list(engine._node.values()), engine._edges)
        got = GraphOfThoughts(engine=engine, gql=gql)
        _REASONERS[id(engine)] = got
    return got


def forget(engine: QueryEngine) -> None:
    """Drop a superseded engine's cached reasoner (called when the graph is rebuilt)."""
    _REASONERS.pop(id(engine), None)


@dataclass
class ChatAnswer:
    """A grounded reply: text + citations + the graph elements to highlight."""

    text: str
    tool: str
    focus: str | None = None
    evidence: list[Citation] = field(default_factory=list)
    highlight_nodes: list[str] = field(default_factory=list)
    highlight_edges: list[list[str]] = field(default_factory=list)
    detail: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    abstained: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "text": self.text,
            "focus": self.focus,
            "evidence": [c.to_dict() for c in self.evidence],
            "highlight": {"nodes": self.highlight_nodes, "edges": self.highlight_edges},
            "detail": self.detail,
            "confidence": round(self.confidence, 3),
            "abstained": self.abstained,
        }


# Query→tool routing lives in l8_retrieval.routing (the single source of truth shared with
# any agent); `classify` is re-exported here for the console's existing callers/tests.
classify = classify_query

__all__ = ["TOOLS", "ChatAnswer", "answer", "classify", "forget"]


def _one_entity(engine: QueryEngine, q: str, focus: str | None) -> str | None:
    rid = engine.resolve(q)
    if rid and rid in engine._entity_ids:
        return rid
    return focus  # a bare follow-up ("why?") resolves against the last focus


def _two_entities(engine: QueryEngine, q: str, focus: str | None) -> tuple[str, str] | None:
    low = q.lower()
    for sep in (
        " connected to ",
        " connects to ",
        " linked to ",
        " between ",
        " and ",
        " to ",
        " from ",
    ):
        if sep in low:
            i = low.index(sep)
            left, right = q[:i], q[i + len(sep) :]
            if sep == " between " and " and " in right.lower():
                j = right.lower().index(" and ")
                left, right = right[:j], right[j + 5 :]
            a, b = engine.resolve(left), engine.resolve(right)
            if a and b and a != b and a in engine._entity_ids and b in engine._entity_ids:
                return a, b
    one = _one_entity(engine, q, None)
    if one and focus and one != focus:
        return focus, one
    return None


def answer(
    engine: QueryEngine,
    question: str,
    *,
    mode: str = "adaptive",
    tool: str = "auto",
    focus: str | None = None,
) -> ChatAnswer:
    """Route ``question`` to a graph tool and return a grounded, cited :class:`ChatAnswer`.

    The reply is scored for grounding: a *factual* answer with no citation evidence **abstains**
    ("insufficient evidence") rather than surfacing an unsupported guess (Sprint 3.3).
    """
    q = question.strip()
    if not q:
        return ChatAnswer(text="Ask a question about the graph.", tool="auto")
    return _grounded(_dispatch(engine, q, mode=mode, tool=tool, focus=focus))


def _dispatch(
    engine: QueryEngine, q: str, *, mode: str, tool: str, focus: str | None
) -> ChatAnswer:
    chosen = classify(q, tool)
    if chosen == "gql":
        return _gql(engine, q)
    if chosen == "path":
        pair = _two_entities(engine, q, focus)
        if pair:
            return _path(engine, *pair)
        chosen = "reason"  # couldn't find two entities — reason instead
    if chosen == "why":
        e = _one_entity(engine, q, focus)
        return _why(engine, e) if e else _reason(engine, q, mode)
    if chosen == "neighbors":
        e = _one_entity(engine, q, focus)
        return _neighbors(engine, e) if e else _reason(engine, q, mode)
    if chosen == "timeline":
        e = _one_entity(engine, q, focus)
        return _timeline(engine, e) if e else _reason(engine, q, mode)
    if chosen == "contradictions":
        return _contradictions(engine)
    if chosen == "narrate":
        return _narrate(engine, q)
    if chosen == "conflicts":
        return _conflicts(engine)
    if chosen == "trace":
        return _trace(engine, q)
    if chosen == "decisions":
        return _find_decisions(engine, q)
    if chosen == "communities":
        return _communities(engine)
    if chosen == "stats":
        return _stats(engine)
    if chosen == "search":
        return _search(engine, q)
    return _reason(engine, q, mode)


def _grounded(ans: ChatAnswer) -> ChatAnswer:
    """Attach a grounding confidence + abstain factual answers with no citation support."""
    g = assess(ans.tool, evidence_count=len(ans.evidence), has_focus=ans.focus is not None)
    ans.confidence = g.confidence
    ans.abstained = g.abstain
    if g.abstain:
        ans.text = ABSTENTION_TEXT
        ans.highlight_nodes = []
        ans.highlight_edges = []
    return ans


# -- per-tool answer builders (each grounded + cited) ------------------------


def _reason(engine: QueryEngine, q: str, mode: str) -> ChatAnswer:
    res = _reasoner_for(engine).reason(
        q, mode=mode if mode in ("adaptive", "static") else "adaptive"
    )
    nodes: list[str] = []
    for t in res.graph.thoughts:
        for f in t.focus:
            if f not in nodes:
                nodes.append(f)
    detail = [
        {"role": t.role.value, "content": t.content, "evidence": [c.to_dict() for c in t.evidence]}
        for t in res.graph.thoughts
    ]
    return ChatAnswer(
        text=res.answer,
        tool="reason",
        focus=nodes[0] if nodes else None,
        evidence=list(res.evidence),
        highlight_nodes=nodes,
        detail=detail,
    )


def _search(engine: QueryEngine, q: str) -> ChatAnswer:
    res = engine.search(q, k=6)
    ents = [h for h in res.hits if h.kind == "entity"]
    chunks = [h for h in res.hits if h.kind == "chunk"]
    names = ", ".join(h.name for h in ents[:5]) or "no entities"
    text = f'Top matches for "{q}" ({res.routing} routing): {names}.'
    # Ground on ALL hit citations (entities too), not just chunks — otherwise an entity-only
    # match with no passage chunk would wrongly abstain despite having cited entities.
    evidence = [c for h in res.hits for c in h.citations]
    return ChatAnswer(
        text=text,
        tool="search",
        focus=ents[0].node_id if ents else None,
        evidence=evidence,
        highlight_nodes=[h.node_id for h in ents],
        detail=[
            {"snippet": h.snippet, "evidence": [c.to_dict() for c in h.citations]} for h in chunks
        ],
    )


def _path(engine: QueryEngine, a: str, b: str) -> ChatAnswer:
    res = engine.path(a, b, k=1)
    na, nb = engine._name(a), engine._name(b)
    if not res.paths:
        return ChatAnswer(
            text=f"No path found from {na} to {nb}.", tool="path", focus=a, highlight_nodes=[a, b]
        )
    p = res.paths[0]
    ids = [rid for name in p.nodes if (rid := engine.resolve(name))]
    edges = [[ids[i], ids[i + 1]] for i in range(len(ids) - 1)]
    text = f"{na} connects to {nb} via {' → '.join(p.nodes)} (likelihood {round(p.likelihood, 4)})."
    evidence = [c for step in p.steps for c in step.citations]
    return ChatAnswer(
        text=text,
        tool="path",
        focus=a,
        evidence=evidence,
        highlight_nodes=ids,
        highlight_edges=edges,
        detail=[
            {
                "subject": s.subject,
                "predicate": s.predicate,
                "object": s.object,
                "evidence": [c.to_dict() for c in s.citations],
            }
            for s in p.steps
        ],
    )


def _why(engine: QueryEngine, e: str) -> ChatAnswer:
    res = engine.why(e)
    name = engine._name(e)
    if not res.claims:
        return ChatAnswer(
            text=f"No cited claims about {name}.", tool="why", focus=e, highlight_nodes=[e]
        )
    text = (
        f"{len(res.claims)} cited claim(s) about {name}: "
        + "; ".join(f"{c.subject} {c.predicate} {c.object}" for c in res.claims[:4])
        + "."
    )
    evidence = [c for cl in res.claims for c in cl.citations]
    return ChatAnswer(
        text=text,
        tool="why",
        focus=e,
        evidence=evidence,
        highlight_nodes=[e],
        detail=[
            {
                "subject": c.subject,
                "predicate": c.predicate,
                "object": c.object,
                "status": c.status,
                "t_valid": c.t_valid,
                "t_invalid": c.t_invalid,
                "evidence": [x.to_dict() for x in c.citations],
            }
            for c in res.claims
        ],
    )


def _neighbors(engine: QueryEngine, e: str) -> ChatAnswer:
    res = engine.neighbors(e, k=10)
    name = engine._name(e)
    if not res.neighbors:
        return ChatAnswer(
            text=f"{name} has no visible relations.", tool="neighbors", focus=e, highlight_nodes=[e]
        )
    text = (
        f"{name} is related to: "
        + "; ".join(f"{n.predicate} {n.other_name}" for n in res.neighbors[:6])
        + "."
    )
    return ChatAnswer(
        text=text,
        tool="neighbors",
        focus=e,
        evidence=[c for n in res.neighbors for c in n.citations],
        highlight_nodes=[e] + [n.other_id for n in res.neighbors],
        detail=[
            {
                "predicate": n.predicate,
                "other": n.other_name,
                "direction": n.direction,
                "evidence": [c.to_dict() for c in n.citations],
            }
            for n in res.neighbors
        ],
    )


def _timeline(engine: QueryEngine, e: str) -> ChatAnswer:
    res = engine.timeline(e)
    name = engine._name(e)
    if not res.events:
        return ChatAnswer(
            text=f"No dated events for {name}.", tool="timeline", focus=e, highlight_nodes=[e]
        )
    text = (
        f"Timeline of {name}: "
        + "; ".join(
            f"{c.t_valid or '?'} {c.predicate} {c.object}"
            + (" (superseded)" if c.status == "superseded" else "")
            for c in res.events[:6]
        )
        + "."
    )
    return ChatAnswer(
        text=text,
        tool="timeline",
        focus=e,
        evidence=[c for cl in res.events for c in cl.citations],
        highlight_nodes=[e],
        detail=[
            {
                "t_valid": c.t_valid,
                "t_invalid": c.t_invalid,
                "predicate": c.predicate,
                "object": c.object,
                "status": c.status,
            }
            for c in res.events
        ],
    )


def _contradictions(engine: QueryEngine) -> ChatAnswer:
    res = engine.contradictions()
    if not res.pairs:
        return ChatAnswer(text="No contradictions found.", tool="contradictions")
    text = (
        f"{len(res.pairs)} contradiction(s): "
        + "; ".join(
            f"{p.claim_a.subject} {p.claim_a.predicate} {p.claim_a.object}" for p in res.pairs[:4]
        )
        + "."
    )
    return ChatAnswer(
        text=text,
        tool="contradictions",
        detail=[{"a": p.claim_a.to_dict(), "b": p.claim_b.to_dict()} for p in res.pairs],
    )


def _narrate(engine: QueryEngine, q: str) -> ChatAnswer:
    """Opt-in LLM answer: compose a grounded, cited reply over the retrieved evidence.

    GENERATED-quarantined; needs an LLM endpoint in the environment (MODEL_BASE_URL /
    MODEL_NAME / API_KEY). No endpoint -> a clear message, never a fabricated answer.
    """
    from textgraph.core.config import Config
    from textgraph.l4_llm_optional import resolve_client
    from textgraph.l8_retrieval.narrate import narrate as _compose

    res = engine.search(q, k=6)
    passages = [(h.snippet, list(h.citations)) for h in res.hits if h.snippet]
    client = resolve_client(Config())
    if client is None:
        return ChatAnswer(
            text="LLM narration needs an endpoint: set MODEL_BASE_URL / MODEL_NAME / API_KEY "
            "in the environment before launching the console.",
            tool="narrate",
        )
    ans = _compose(client, q, passages)
    if ans is None:
        return ChatAnswer(text="No retrieved evidence to ground an answer.", tool="narrate")
    return ChatAnswer(
        text=ans.text,
        tool="narrate",
        evidence=list(ans.citations),
        highlight_nodes=[h.node_id for h in res.hits if h.kind == "entity"],
        detail=[{"note": "GENERATED — composed by the LLM from the cited evidence above."}],
    )


def _conflicts(engine: QueryEngine) -> ChatAnswer:
    res = engine.conflicts()
    if not res.conflicts:
        return ChatAnswer(text="No single-truth conflicts found.", tool="conflicts")

    def _line(c: Any) -> str:
        base = f"[{c.severity}] {c.subject} {c.predicate} {{{', '.join(c.objects)}}}"
        return base + (f" -> {c.resolved_object}" if c.resolved_object else "")

    lines = "; ".join(_line(c) for c in res.conflicts[:4])
    text = f"{len(res.conflicts)} conflict(s): {lines}."
    # Highlight the subject + contended objects on the canvas where they resolve to entities.
    highlight: list[str] = []
    for c in res.conflicts:
        for name in [c.subject, *c.objects]:
            rid = engine.resolve(name)
            if rid and rid not in highlight:
                highlight.append(rid)
    evidence = [cit for c in res.conflicts for cl in c.claims for cit in cl.citations]
    return ChatAnswer(
        text=text,
        tool="conflicts",
        evidence=evidence,
        highlight_nodes=highlight,
        detail=[c.to_dict() for c in res.conflicts],
    )


def _trace(engine: QueryEngine, q: str) -> ChatAnswer:
    res = engine.trace_decision_chain(q)
    if not res.found or res.decision is None:
        return ChatAnswer(text="No matching decision found to trace.", tool="trace")
    d = res.decision
    parts = []
    if res.ancestors:
        parts.append(f"{len(res.ancestors)} precedent/cause(s)")
    if res.descendants:
        parts.append(f"{len(res.descendants)} effect(s)")
    summary = ", ".join(parts) if parts else "no recorded causes or effects"
    text = f'Decision "{d.name}": {summary}.'
    hops = res.ancestors + res.descendants
    evidence = list(d.citations) + [c for h in hops for c in h.citations]
    return ChatAnswer(
        text=text,
        tool="trace",
        focus=d.decision_id,
        evidence=evidence,
        highlight_nodes=[d.decision_id, *(h.from_id for h in hops), *(h.to_id for h in hops)],
        highlight_edges=[[h.from_id, h.to_id] for h in hops],
        detail=[
            {
                "direction": "ancestor" if h in res.ancestors else "descendant",
                "relation": h.relation,
                "from": h.from_name,
                "to": h.to_name,
                "evidence": [c.to_dict() for c in h.citations],
            }
            for h in hops
        ],
    )


def _find_decisions(engine: QueryEngine, q: str) -> ChatAnswer:
    res = engine.find_similar_decisions(q, k=6)
    if not res.hits:
        return ChatAnswer(text="No matching decisions found.", tool="decisions")
    text = (
        f'{len(res.hits)} decision(s) matching "{q}": '
        + "; ".join(h.name[:70] for h in res.hits[:4])
        + "."
    )
    return ChatAnswer(
        text=text,
        tool="decisions",
        focus=res.hits[0].decision_id,
        evidence=[c for h in res.hits for c in h.citations],
        highlight_nodes=[h.decision_id for h in res.hits],
        detail=[
            {
                "category": h.category,
                "name": h.name,
                "score": h.score,
                "evidence": [c.to_dict() for c in h.citations],
            }
            for h in res.hits
        ],
    )


def _communities(engine: QueryEngine) -> ChatAnswer:
    res = engine.communities()
    text = (
        f"{len(res.communities)} communities: "
        + "; ".join(
            f"{c.label or '#' + str(c.community_id)} ({c.size})" for c in res.communities[:6]
        )
        + "."
    )
    return ChatAnswer(
        text=text,
        tool="communities",
        detail=[{"label": c.label, "size": c.size, "members": c.members} for c in res.communities],
    )


def _stats(engine: QueryEngine) -> ChatAnswer:
    res = engine.stats()
    c = res.counts
    text = (
        f"{c.get('entities', 0)} entities, {c.get('edges', 0)} relations, "
        f"{c.get('claims', 0)} claims. Top: "
        + ", ".join(e["name"] for e in res.top_entities[:5])
        + "."
    )
    return ChatAnswer(
        text=text,
        tool="stats",
        highlight_nodes=[e["node_id"] for e in res.top_entities],
        detail=[{"counts": c, "top_entities": res.top_entities}],
    )


def _gql(engine: QueryEngine, q: str) -> ChatAnswer:
    gql = GQLEngine(list(engine._node.values()), engine._edges)
    try:
        res = gql.query(q)
    except GQLError as exc:
        return ChatAnswer(text=f"GQL error: {exc}", tool="gql")
    rows = res.rows[:20]
    text = f"{len(res.rows)} row(s). Columns: {', '.join(res.columns)}."
    return ChatAnswer(
        text=text,
        tool="gql",
        detail=[{"columns": res.columns, "rows": [[str(v) for v in r] for r in rows]}],
    )
