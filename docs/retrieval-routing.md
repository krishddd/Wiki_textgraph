# Retrieval routing

TextGraph routes each query to the retrieval strategy that fits it, rather than forcing one
pipeline on every question. The decision is **deterministic and auditable** (no model, no
clock) and lives in one place — `textgraph/l8_retrieval/routing.py` — shared by the console
"Ask" chat and any agent, so routing never drifts between surfaces.

## The decision

`route(question)` returns a `RoutePlan { tool, strategy, reason }`:

- **tool** — which graph tool answers the question.
- **strategy** — the retrieval *family* that tool belongs to (below).
- **reason** — a short human-readable justification (shown to the user; G6).

`classify_query(question, forced="auto")` is the underlying tool picker; pass `forced=<tool>`
to override the rules (the chat's tool dropdown does this).

## Rules (ordered; first match wins)

| Cue in the question | Tool | Strategy family |
|---|---|---|
| starts with `MATCH` / contains `RETURN` | `gql` | structured-graph (declarative pattern match) |
| "connected to", "link between", "path from", "between …" | `path` | graph-traversal (multi-hop, max-likelihood) |
| starts with "why", or "explain" | `why` | graph-traversal (claim neighbourhood) |
| "neighbours", "related to" | `neighbors` | graph-traversal (one hop) |
| "timeline", "when did", "over time", "history of" | `timeline` | graph-traversal (temporal slice) |
| "contradict", "conflict" | `contradictions` | graph-analytics (precomputed) |
| "communit(y/ies)", "cluster", "topic" | `communities` | graph-analytics (precomputed) |
| "stats", "how many", "count" | `stats` | graph-analytics (aggregate) |
| *(anything else)* | `reason` | hybrid-multi-tool (Graph-of-Thoughts) |

`search` (BM25 + Personalized PageRank + Reciprocal Rank Fusion — the **hybrid-lexical-graph**
family) is reachable via `forced="search"` or as the fallback anchor inside `reason`.

## Strategy families

- **structured-graph** — GQL pattern matching over the property graph.
- **graph-traversal** — walk the entity graph (path / neighbors / why / timeline).
- **graph-analytics** — read precomputed L7 properties (communities, contradictions, stats).
- **hybrid-lexical-graph** — `search`: lexical BM25 fused with graph Personalized PageRank.
- **hybrid-multi-tool** — `reason`: the Graph-of-Thoughts loop composing several tools, with
  a complexity gate that only spawns the expensive traversal/verification branches when the
  question is hard.

## Why deterministic rules (not an LLM classifier)

Routing is a *dispatch* decision, not a reasoning one, so a small ordered rule set is enough
and keeps the whole path reproducible (G1) and explainable (G6): the `reason` string can be
surfaced so a user always knows *why* a given retrieval strategy was chosen. An open question
falls through to the Graph-of-Thoughts `reason` tool, which itself hybridises retrieval and
degrades gracefully to lexical search when a question names no entity.
