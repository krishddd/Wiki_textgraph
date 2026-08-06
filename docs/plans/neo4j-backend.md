# Design — optional Neo4j scale-out backend (`textgraph serve`)

**Status:** design only (Sprint 2.4) — no code yet. DuckDB stays the default; Neo4j is an
*opt-in* backend for users who outgrow single-node DuckDB. The moat is local-first +
deterministic + byte-level provenance; this design must not trade any of it away.

---

## 1. Why, and the hard constraint

DuckDB/Parquet on disk comfortably handles the v1 target (~10k docs, low-millions of edges)
and keeps the whole product local-first (G2). Some users will need scale-out — concurrent
queries, larger-than-memory graphs, a shared server. Neo4j (or FalkorDB/Memgraph) is the
obvious optional backend.

**The non-negotiable:** the graph TextGraph builds is *derived, deterministic, and
provenance-carrying*. Any backend is a **materialization target for an already-built
`graph.json`**, never the source of truth and never part of the deterministic build. So:

- The build (`textgraph build`) stays local, deterministic, and DB-free. `graph.json` is
  produced first and is byte-identical regardless of backend (G1).
- `textgraph serve --backend neo4j` **loads** that artifact into Neo4j for querying at scale.
- Every node/edge keeps its `[doc:start-end]` citation + `hash` as properties, so provenance
  re-verification (G3) works identically over Neo4j.

This inverts the usual GraphRAG design (where the DB *is* the pipeline). Keeping the DB
downstream of a deterministic artifact is exactly the differentiator, so it's load-bearing.

## 2. Shape

```
textgraph build ./corpus          # deterministic, local -> graph.json (unchanged)
textgraph serve ./graph.json --backend duckdb   # default: embedded, local
textgraph serve ./graph.json --backend neo4j --uri bolt://…   # opt-in scale-out
```

`serve` exposes the **same eight typed tools + reason + gql** over HTTP (the console API
already is this shape) — only the storage/query engine behind them changes. A
`GraphBackend` protocol (already anticipated by the `GraphStore` ABC) gets a Neo4j
implementation behind the existing `[neo4j]` extra; the L8 `QueryEngine` operations map to
Cypher. Determinism of *results* is preserved by pinning ORDER BY on every query (Neo4j does
not guarantee row order otherwise).

## 3. Feature comparison vs **Neo4j GraphRAG Python**

What to adopt patterns from vs. what conflicts with G1–G3:

| Neo4j GraphRAG feature | Verdict | Notes |
|---|---|---|
| **VectorCypherRetriever** (vector search → Cypher expansion) | **Adopt the pattern** | Mirrors our hybrid search: seed by similarity, expand by graph. We already do BM25+PPR; a Neo4j backend can push the expansion into Cypher. Keep our RRF fusion so ranking stays reproducible. |
| **ToolsRetriever** (LLM picks a retriever/tool per query) | **Adopt, but deterministic** | This is exactly our `routing.py`, minus the LLM. Keep the rule-based router (G1) as the default; an LLM router can be an opt-in narration-mode extra, never the default. |
| **GraphPruner** (schema-align / trim extracted graph) | **Partial** | We prune deterministically at build (confidence tags, god-node guard). Don't move pruning into the serving DB — it must stay in the deterministic build so `graph.json` is the pruned truth. |
| **EntityResolver** (LLM/embedding entity dedup) | **Conflicts as default** | Our L5 ER is deterministic (blocking + Jaro-Winkler + relational) and runs at build. An embedding/LLM resolver is non-deterministic; only viable as an opt-in `[er]` upgrade, never folded into the default build (G1). |
| **Schema-guided extraction** (LLM extracts to a fixed schema) | **Conflicts as default** | Our extraction default is model-free rules (G2). Schema-guided LLM extraction is the opt-in `[ie]`/L4 path; it must stay `GENERATED`-tagged and out of the determinism gate. |
| **Lexical graph** (chunk/document nodes linked to entities) | **Already have it** | Our dual-node graph (Chunk + Entity nodes, `HAS_CHUNK`/`MENTIONS`) is exactly this. Maps 1:1 to Neo4j labels. |
| **Cypher 25 `SEARCH` clause** (native hybrid search) | **Adopt when available** | If serving on Neo4j 5.26+/Cypher 25, push hybrid search server-side. Guard on version; fall back to app-side fusion. Result ordering must stay pinned for reproducibility. |
| **Full-text + vector indexes** | **Adopt** | Create them on load for scale; they're an index over the *same* provenance-carrying nodes, so G3 is unaffected. |

**Net:** adopt the *retrieval-shape* patterns (vector→graph expansion, per-query routing,
lexical graph, native indexes) because they're compatible; **reject as defaults** the
patterns that move non-determinism or LLMs into the build (schema-guided extraction,
embedding entity resolution, DB-side pruning) — those stay opt-in and out of the G1 path.

## 4. What does NOT move to Neo4j (protect the moat)

- **The build.** Ingestion → IE → resolution → claims → analytics stays local + deterministic.
- **Provenance verification.** Byte-span re-hash (G3) is done against source docs, not the DB.
- **The determinism gate.** CI still builds `graph.json` locally and byte-compares; Neo4j is
  never in that loop.
- **Default install.** `neo4j` driver stays in the `[neo4j]` extra; the default stays lean (G2).

## 5. Open questions / risks

1. **Result determinism on Neo4j.** Must pin `ORDER BY` on every query and pin PPR/community
   parameters; Neo4j GDS PageRank must be seeded/iteration-capped to match our pure-Python
   results, or we accept "same ranking, backend-specific ties" and document it.
2. **Bi-temporal queries.** Our `[t_valid, t_invalid)` windows map to relationship properties
   + a `WHERE` filter; validate performance with a temporal index.
3. **FGAC (Phase 9).** Security-aware PPR is currently in-process. On Neo4j, either replicate
   the masked-traversal in Cypher (parameterize authorized node ids) or keep policy filtering
   app-side in front of the DB — decide before building.
4. **Sync model.** `serve` loads a snapshot; incremental updates (`watch`) need an
   idempotent upsert-by-`node_id`/`edge_id` path into Neo4j.

## 6. Recommendation

Build the `GraphBackend` protocol + a **read-only Neo4j loader/query backend** first (load
`graph.json` → labeled property graph with citations; map the 8 tools to pinned-order
Cypher), behind `[neo4j]`, as `textgraph serve --backend neo4j`. Defer write-back/incremental
and GDS-accelerated PPR to a second pass. Keep DuckDB the default backend and the only one in
the determinism gate. Revisit FalkorDB/Memgraph as alternative targets once the protocol
exists — the abstraction is the deliverable, not the specific engine.
