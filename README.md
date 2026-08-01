# TextGraph

> Turn any body of text into a **queryable knowledge graph with byte-level provenance on every claim** — local-first, deterministic, and agent-legible.

TextGraph is the natural-language successor to [**llm-wiki**](https://github.com/krishddd/llm-wiki). Where `llm-wiki` gave an agent cited, streaming answers over Wikipedia knowledge, TextGraph generalizes that idea to **any textual corpus** — documents, specs, contracts, transcripts, logs, threads, wikis, code comments, meeting notes — and emits a structured, versioned graph an agent can traverse, not just a stream of prose. It is built to be **best-in-class at solving complex data tasks**: multi-hop questions, contradiction detection, temporal reasoning, and provenance-backed retrieval.

## Why it exists

`llm-wiki` proved the value of citation-grounded, MCP-exposed knowledge retrieval. TextGraph extends that tool along three axes:

| llm-wiki | TextGraph |
|---|---|
| Answers over Wikipedia | Ingests **any** textual corpus |
| Streamed prose with sources | **Queryable knowledge graph** with byte-range citations on every edge |
| LLM-in-the-loop | **Zero LLM calls required** — deterministic parsers + encoder IE by default (`--no-llm` always works) |
| Point-in-time answer | **Bi-temporal** — what is true, what *was* true, when it changed, and why |

## The one-paragraph pitch

TextGraph turns any body of text into a queryable knowledge graph with byte-level provenance on every claim. Extraction runs entirely on the user's machine using deterministic structural parsers and encoder-based information-extraction models — no LLM calls are required and text never leaves the machine by default. Every edge is tagged `STRUCTURAL`, `EXTRACTED`, `INFERRED`, or `GENERATED`, carries the exact source span that supports it, and is versioned bi-temporally so an agent can ask not just *what is true*, but *what was true, when it changed, and why*.

## Design goals (non-negotiable)

- **G1 — Determinism.** Same corpus + same version ⇒ byte-identical `graph.json`.
- **G2 — Local-first.** Zero network calls by default; any LLM pass is opt-in.
- **G3 — Provenance.** No assertion without a re-verifiable byte-range citation.
- **G4 — Confidence stratification.** Every edge tagged `STRUCTURAL / EXTRACTED / INFERRED / GENERATED`.
- **G5 — Incrementality.** One changed file never forces a full rebuild.
- **G6 — Agent-legible output.** Bounded, ranked, cited context packs — never raw Cypher.
- **G7 — Bounded, auditable cost.** Per-stage token/time/dollar budgets in a run manifest.

## Architecture at a glance

A strictly bottom-up layer stack, each layer a pure function of the one below it plus a pinned config hash:

```
any text → L0  INGEST & NORMALIZE          → CanonicalDoc (UTF-8 + layout tree + offsets)
           L1  DETERMINISTIC STRUCTURE      → structural spine graph (0 models)
           L2  LINGUISTIC SUBSTRATE         → sentences, deps, coref, discourse
           L3  ENCODER IE                   → typed mentions + typed relations
           L4  OPTIONAL LLM SEMANTIC        → abstractions, WHY-nodes (opt-in)
           L5  ENTITY RESOLUTION            → canonical nodes, SAME_AS lattice
           L6  GRAPH ASSEMBLY (bi-temporal) → reified Claim graph + provenance
           L7  ANALYTICS                    → communities, god nodes, bridges
           L8  RETRIEVAL (hybrid + PPR)     → ranked, cited context packs
           L9  ARTIFACTS + MCP/SKILL        → graph.json / graph.html / REPORT.md / tools
```

## Status

🚧 **Early scaffolding.** This repository currently holds the engineering specification and blueprint. Implementation follows the phased roadmap (Phase 0: repo + CI foundation → Phase 6: v1.0 → Phases 7–10: enterprise extensions).

## Specification documents

- [`textgraph-engineering-research.md`](textgraph-engineering-research.md) — the primary engineering specification (L0–L9 stack, model choices, storage, retrieval, evaluation).
- `TextGraph_Engineering_Blueprint.pdf` — slide-deck rendering of the architecture (visual cross-check + UI reference).
- `TextGraph Architecture Gap Analysis.docx` — enterprise extension research (GQL surface, vision-native ingestion, fine-grained access control, Graph-of-Thoughts).

## Related work

- [llm-wiki](https://github.com/krishddd/llm-wiki) — the predecessor tool this project extends.
- **Graphify** — the closest prior art (tree-sitter over *code*); TextGraph recovers its guarantees (determinism, locality, provenance, cost linearity) for the domain of arbitrary natural language.

## License

MIT
