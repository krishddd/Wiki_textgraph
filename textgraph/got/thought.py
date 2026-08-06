"""Thought vertices and the thought graph (Phase 10, Graph-of-Thoughts).

The gap analysis (§4.1) formalises a GoT reasoning process as a tuple of thought vertices
``V``, directed dependency edges ``E`` (a downstream thought derived from upstream ones),
a role function ``sigma`` annotating each vertex (Plan / SubProblem / Hypothesis /
VerificationStep / DistilledSummary), and the four graph-transformation operators. This
module is the data model for exactly that: an immutable :class:`Thought` and a
:class:`ThoughtGraph` that assigns deterministic vertex ids and serialises the whole
reasoning trace.

The single invariant that makes the trace *verifiable* (ESCARGOT, §4.2): every substantive
thought carries **evidence** — real ``[doc:start-end]`` citations pulled from the graph by
the tool that produced it. A thought with no graph evidence is not a fact; it is pruned by
Distillation. So a finished :class:`ThoughtGraph` is a reasoning chain whose every step
points at re-verifiable source bytes (G3), never free-floating model text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from textgraph.l8_retrieval.model import Citation


class Role(StrEnum):
    """The semantic role ``sigma`` assigns to a thought vertex (§4.1)."""

    PLAN = "Plan"
    SUBPROBLEM = "SubProblem"
    HYPOTHESIS = "Hypothesis"
    VERIFICATION = "VerificationStep"
    SUMMARY = "DistilledSummary"


# Roles whose thoughts make a factual claim and therefore MUST cite graph evidence.
# Plan is a meta step (it frames the question) and may be evidence-light.
_SUBSTANTIVE = frozenset({Role.SUBPROBLEM, Role.HYPOTHESIS, Role.VERIFICATION, Role.SUMMARY})


@dataclass(frozen=True)
class Thought:
    """A single reasoning vertex, bound to the graph evidence that justifies it."""

    id: str
    role: Role
    content: str
    operator: str  # "root" | "generate" | "aggregate" | "refine" | "distill"
    parents: tuple[str, ...] = ()
    evidence: tuple[Citation, ...] = ()
    focus: tuple[str, ...] = ()  # entity node ids this thought reasons about
    score: float = 0.0

    @property
    def grounded(self) -> bool:
        """True unless this is a substantive thought with no graph citation."""
        return self.role not in _SUBSTANTIVE or bool(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role.value,
            "content": self.content,
            "operator": self.operator,
            "parents": list(self.parents),
            "focus": list(self.focus),
            "score": round(self.score, 6),
            "evidence": [c.to_dict() for c in self.evidence],
        }


@dataclass
class ThoughtGraph:
    """An ordered set of thoughts with deterministic ids (``t0``, ``t1`` …)."""

    thoughts: list[Thought] = field(default_factory=list)
    _counter: int = 0

    def new_id(self) -> str:
        tid = f"t{self._counter}"
        self._counter += 1
        return tid

    def add(
        self,
        role: Role,
        content: str,
        operator: str,
        *,
        parents: tuple[str, ...] = (),
        evidence: tuple[Citation, ...] = (),
        focus: tuple[str, ...] = (),
        score: float = 0.0,
    ) -> Thought:
        thought = Thought(
            id=self.new_id(),
            role=role,
            content=content,
            operator=operator,
            parents=parents,
            evidence=evidence,
            focus=focus,
            score=score,
        )
        self.thoughts.append(thought)
        return thought

    def get(self, tid: str) -> Thought | None:
        return next((t for t in self.thoughts if t.id == tid), None)

    @property
    def fully_grounded(self) -> bool:
        """Every substantive thought cites at least one real graph span (ESCARGOT)."""
        return all(t.grounded for t in self.thoughts)

    def to_dict(self) -> dict[str, Any]:
        # Edges are the parent->child dependencies, deterministically ordered.
        edges = [{"source": p, "target": t.id} for t in self.thoughts for p in t.parents]
        return {
            "vertices": [t.to_dict() for t in self.thoughts],
            "edges": edges,
        }
