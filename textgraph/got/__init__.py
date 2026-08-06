"""Graph-of-Thoughts agent reasoning (Phase 10).

A deterministic, complexity-gated reasoner (DGoT/AGoT/ESCARGOT lineage, gap analysis §4)
that answers a query by building a graph of thought vertices — each bound to **real** graph
evidence retrieved with the L8/L-standards tools (``search`` / ``neighbors`` / ``path`` /
``why`` / ``gql``). Every substantive step cites re-verifiable ``[doc:span]`` bytes (G3),
and task complexity is measured at runtime so easy queries stay cheap while hard ones spawn
the expensive Aggregation/Refinement branches. Read-only over the assembled graph — so
``graph.json`` and determinism are untouched. See :mod:`textgraph.got.reason`.
"""

from textgraph.got.reason import GraphOfThoughts, ReasoningResult
from textgraph.got.thought import Role, Thought, ThoughtGraph

__all__ = ["GraphOfThoughts", "ReasoningResult", "Role", "Thought", "ThoughtGraph"]
