"""The Graph-of-Thoughts reasoner (Phase 10) — complexity-gated, KG-grounded.

A reference agent loop in the DGoT/AGoT/ESCARGOT lineage (gap analysis §4.2): it reasons
over a query by building a :class:`~textgraph.got.thought.ThoughtGraph` whose vertices are
bound to **real graph evidence**, retrieved with the very tools an agent would call —
``search`` to find the focus entities, ``neighbors`` to characterise each (Generation),
``path`` to connect them (Aggregation), ``why`` + a ``gql`` triple check to verify the
connection (Refinement), then Distillation to prune and summarise under a budget.

Two properties make this more than a wrapper:

* **Every step cites real spans (ESCARGOT).** Each operator binds the ``[doc:start-end]``
  citations from its tool result onto the thought it produces; a thought that gathered no
  evidence is dropped. The finished trace is therefore verifiable end to end (G3).
* **Adaptive cost (DGoT/AGoT).** Task complexity — how many focus entities the query
  resolves to — is measured at runtime. A simple query runs a cheap linear chain; only when
  complexity crosses a threshold does the loop spawn parallel branches and the (expensive)
  Aggregation/Refinement operators. The ``static`` mode expands the full topology
  regardless, so the benchmark can show adaptive < static empirically.

Pure-Python and deterministic: every tool it calls is deterministic and sorted, thought ids
are sequential, and there is no wall-clock or randomness — so reasoning is reproducible
(G1) and, being read-only over the assembled graph, never touches ``graph.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textgraph.got.thought import Role, Thought, ThoughtGraph
from textgraph.gql.engine import GQLEngine
from textgraph.gql.errors import GQLError
from textgraph.l8_retrieval.bm25 import tokenize
from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.l8_retrieval.model import Citation
from textgraph.store.base import Edge, Node

_MAX_EVIDENCE = 6  # citations kept per thought (legibility / token budget, G7)


def _dedup(cits: list[Citation]) -> tuple[Citation, ...]:
    """De-duplicate and stably order a citation list (deterministic)."""
    seen: set[tuple[str, int, int, str]] = set()
    out: list[Citation] = []
    for c in cits:
        key = (c.doc_id, c.start, c.end, c.hash)
        if key not in seen:
            seen.add(key)
            out.append(c)
    out.sort(key=lambda c: (c.doc_id, c.start, c.end))
    return tuple(out[:_MAX_EVIDENCE])


@dataclass
class ReasoningResult:
    """The finished reasoning trace: the thought graph, the answer, and its cost."""

    query: str
    mode: str
    complexity: int
    answer: str
    graph: ThoughtGraph
    tool_calls: int
    evidence: tuple[Citation, ...] = field(default_factory=tuple)

    @property
    def grounded(self) -> bool:
        return self.graph.fully_grounded

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "reason",
            "query": self.query,
            "mode": self.mode,
            "complexity": self.complexity,
            "answer": self.answer,
            "tool_calls": self.tool_calls,
            "grounded": self.grounded,
            "evidence": [c.to_dict() for c in self.evidence],
            "graph": self.graph.to_dict(),
        }


class GraphOfThoughts:
    """A deterministic, complexity-gated Graph-of-Thoughts reasoner over a TextGraph."""

    def __init__(
        self,
        nodes: list[Node],
        edges: list[Edge],
        *,
        max_tool_calls: int = 16,
        complexity_threshold: int = 2,
        branch_cap: int = 3,
        static_cap: int = 5,
    ) -> None:
        self.engine = QueryEngine(nodes, edges)
        self.gql = GQLEngine(nodes, edges)
        self.max_tool_calls = max_tool_calls
        self.complexity_threshold = complexity_threshold
        self.branch_cap = branch_cap
        self.static_cap = static_cap
        self._calls = 0
        self._hyp_pred: dict[str, str] = {}  # hypothesis id -> its path's dominant predicate

    # -- public -----------------------------------------------------------------

    def reason(self, query: str, *, mode: str = "adaptive") -> ReasoningResult:
        """Reason over ``query``; ``mode`` is ``adaptive`` (gated) or ``static`` (full)."""
        self._calls = 0
        self._hyp_pred = {}
        graph = ThoughtGraph()
        focus, material, plan_cites = self._focus_entities(query)
        # Runtime complexity (AGoT): how many entities the query itself names. This — not the
        # breadth of what search happened to surface — is what gates topology expansion.
        complexity = len(focus)
        # If the query names no entity, still reason: anchor on the single best entity search
        # surfaced, so an exploratory question ("who transferred funds?") gets a grounded
        # answer rather than nothing — complexity stays 0, so it runs the cheap linear chain.
        anchor = focus or material[:1]
        plan = graph.add(
            Role.PLAN,
            f"Plan: resolve the query to focus entities, characterise each, connect them, "
            f"then verify. Focus = [{', '.join(self.engine._name(f) for f in anchor) or 'none'}].",
            "root",
            evidence=_dedup(plan_cites),
            focus=tuple(anchor),
            score=float(complexity),
        )
        if not anchor:
            return self._finish(query, mode, complexity, graph)

        # Adaptive gates on complexity and reasons only over the query's focus entities (or
        # the anchor when none are named); static always expands the full topology — the
        # focus PLUS the co-mentioned neighbourhood — regardless of difficulty (the baseline).
        if mode == "static":
            expansion = (focus + material)[: self.static_cap]
        else:
            expansion = (focus or anchor)[: self.branch_cap]

        subs: list[Thought] = []
        for f in expansion:
            if self._over_budget():
                break
            s = self._generate(graph, plan, f)
            if s is not None:
                subs.append(s)

        hypotheses: list[Thought] = []
        expand = mode == "static" or complexity >= self.complexity_threshold
        if expand and len(subs) >= 2:
            for a, b in self._pairs(subs, all_pairs=(mode == "static")):
                if self._over_budget():
                    break
                hyp = self._aggregate(graph, a, b)
                if hyp is not None:
                    hypotheses.append(hyp)

        # Refinement: verify each hypothesis (static) or just the strongest (adaptive). With
        # no connecting hypothesis (e.g. a simple single-entity query), verify the top
        # sub-problem directly, so even the cheap linear chain ends in a cited check.
        to_refine: list[Thought] = hypotheses if mode == "static" else hypotheses[:1]
        if not to_refine and subs:
            to_refine = subs if mode == "static" else subs[:1]
        for t in to_refine:
            if self._over_budget():
                break
            self._refine(graph, t)

        self._distill(graph)
        return self._finish(query, mode, complexity, graph)

    def _over_budget(self) -> bool:
        """True once the tool-call budget is exhausted (bounded reasoning, G7)."""
        return self._calls >= self.max_tool_calls

    # -- focus / complexity -----------------------------------------------------

    def _focus_entities(self, query: str) -> tuple[list[str], list[str], list[Citation]]:
        """Split search hits into (focus, material, citations), deterministically.

        *Focus* = entities the query actually names (a name token overlaps the query) — the
        subject of the reasoning. *Material* = the other entities search surfaced (the
        co-mentioned neighbourhood) — extra breadth the ``static`` topology explores but the
        adaptive one only reaches through the graph.
        """
        result = self._search(query, k=max(self.static_cap * 2, 8))
        qtokens = set(tokenize(query))
        focus: list[str] = []
        material: list[str] = []
        cites: list[Citation] = []
        for hit in result.hits:
            cites.extend(hit.citations)
            if hit.kind != "entity" or hit.node_id in focus or hit.node_id in material:
                continue
            if qtokens & set(tokenize(hit.name)):
                focus.append(hit.node_id)
            else:
                material.append(hit.node_id)
        routed = self.engine.resolve(query)
        if (
            routed
            and routed in self.engine._entity_ids
            and routed not in focus
            and qtokens & set(tokenize(self.engine._name(routed)))
        ):
            focus.insert(0, routed)
        return focus, material, cites

    # -- operators (§4.1) -------------------------------------------------------

    def _generate(self, graph: ThoughtGraph, parent: Thought, focus: str) -> Thought | None:
        """Generation: branch a SubProblem from the plan, grounded by the entity's relations."""
        nbrs = self._neighbors(focus, k=self.branch_cap)
        cites = _dedup([c for n in nbrs.neighbors for c in n.citations])
        if not cites:
            return None
        rels = ", ".join(f"{n.predicate} {n.other_name}" for n in nbrs.neighbors[: self.branch_cap])
        score = sum(n.confidence for n in nbrs.neighbors[: self.branch_cap])
        return graph.add(
            Role.SUBPROBLEM,
            f"Sub-problem: characterise {self.engine._name(focus)} -> {rels}.",
            "generate",
            parents=(parent.id,),
            evidence=cites,
            focus=(focus,),
            score=score,
        )

    def _aggregate(self, graph: ThoughtGraph, a: Thought, b: Thought) -> Thought | None:
        """Aggregation: combine two sub-problems into a Hypothesis via a connecting path."""
        e1, e2 = a.focus[0], b.focus[0]
        result = self._path(e1, e2)
        if not result.paths:
            return None
        best = result.paths[0]
        cites = _dedup([c for step in best.steps for c in step.citations])
        if not cites:
            return None
        chain = " -> ".join(best.nodes)
        hyp = graph.add(
            Role.HYPOTHESIS,
            f"Hypothesis: {self.engine._name(e1)} connects to {self.engine._name(e2)} "
            f"via {chain} (likelihood {round(best.likelihood, 4)}).",
            "aggregate",
            parents=(a.id, b.id),
            evidence=cites,
            focus=(e1, e2),
            score=best.likelihood,
        )
        self._hyp_pred[hyp.id] = best.steps[0].predicate if best.steps else ""
        return hyp

    def _refine(self, graph: ThoughtGraph, hyp: Thought) -> Thought | None:
        """Refinement: verify a hypothesis against claims (why) and KG triples (gql)."""
        endpoint = hyp.focus[0]
        why = self._why(endpoint)
        cites = _dedup([c for cl in why.claims for c in cl.citations] or list(hyp.evidence))
        predicate = self._hyp_pred.get(hyp.id) or None
        triples = self._gql_count(predicate)
        corroborated = triples > 0 and bool(why.claims)
        score = hyp.score * (1.5 if corroborated else 0.5)
        verdict = "corroborated" if corroborated else "unconfirmed"
        return graph.add(
            Role.VERIFICATION,
            f"Verification ({verdict}): {len(why.claims)} cited claim(s) about "
            f"{self.engine._name(endpoint)}; gql finds {triples} "
            f"{predicate or 'relation'} triple(s) in the graph.",
            "refine",
            parents=(hyp.id,),
            evidence=cites,
            focus=hyp.focus,
            score=score,
        )

    def _distill(self, graph: ThoughtGraph) -> Thought:
        """Distillation: prune weak/redundant thoughts, emit a cited summary of survivors."""
        survivors = [
            t
            for t in graph.thoughts
            if t.role in (Role.HYPOTHESIS, Role.VERIFICATION) and t.score > 0 and t.evidence
        ]
        if not survivors:
            # Nothing connected/verified — fall back to the best-grounded sub-problem(s).
            survivors = [t for t in graph.thoughts if t.role == Role.SUBPROBLEM and t.evidence]
        survivors.sort(key=lambda t: (-t.score, t.id))
        keep = survivors[: self.branch_cap]
        cites = _dedup([c for t in keep for c in t.evidence])
        if keep:
            body = "; ".join(t.content.split(":", 1)[-1].strip().rstrip(".") for t in keep)
            content = f"Distilled summary: {body}."
        else:
            content = "Distilled summary: no evidence."
        return graph.add(
            Role.SUMMARY,
            content,
            "distill",
            parents=tuple(t.id for t in keep),  # link the summary to what it distilled
            evidence=cites,
            score=sum(t.score for t in keep),
        )

    # -- helpers ----------------------------------------------------------------

    def _pairs(self, subs: list[Thought], *, all_pairs: bool) -> list[tuple[Thought, Thought]]:
        """Adjacent focus pairs (adaptive: just the top pair; static: all consecutive)."""
        if all_pairs:
            return [(subs[i], subs[j]) for i in range(len(subs)) for j in range(i + 1, len(subs))]
        return [(subs[0], subs[1])]

    def _gql_count(self, predicate: str | None) -> int:
        """Count graph triples of a predicate via GQL (uses only label/type filters)."""
        self._calls += 1
        rel = f":{predicate}" if predicate and predicate.isidentifier() else ""
        try:
            res = self.gql.query(f"MATCH (a:Entity)-[r{rel}]->(b:Entity) RETURN count(*)")
        except GQLError:
            return 0
        if res.rows and res.rows[0]:
            try:
                return int(res.rows[0][0])
            except (TypeError, ValueError):
                return 0
        return 0

    def _finish(
        self, query: str, mode: str, complexity: int, graph: ThoughtGraph
    ) -> ReasoningResult:
        summary = next((t for t in reversed(graph.thoughts) if t.role == Role.SUMMARY), None)
        answer = summary.content if summary else "No graph evidence found for this query."
        evidence = summary.evidence if summary else ()
        return ReasoningResult(
            query=query,
            mode=mode,
            complexity=complexity,
            answer=answer,
            graph=graph,
            tool_calls=self._calls,
            evidence=evidence,
        )

    # -- counted tool calls (the cost the benchmark measures) -------------------

    def _search(self, query: str, *, k: int) -> Any:
        self._calls += 1
        return self.engine.search(query, k=k)

    def _neighbors(self, handle: str, *, k: int) -> Any:
        self._calls += 1
        return self.engine.neighbors(handle, k=k)

    def _path(self, s: str, t: str) -> Any:
        self._calls += 1
        return self.engine.path(s, t)

    def _why(self, handle: str) -> Any:
        self._calls += 1
        return self.engine.why(handle)
