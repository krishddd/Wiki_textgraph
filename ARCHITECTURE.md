# TextGraph Architecture

TextGraph is a stratified extraction stack. Its job is to recover, for arbitrary
natural language, the four guarantees that a code parser like tree-sitter gives
Graphify for free: **determinism, locality, provenance, and cost linearity**.

## The layer stack (L0–L9)

Every layer is a **pure function of the layer below it plus a pinned config hash**.
No layer reaches sideways into another's internals or up into a layer that hasn't
run yet. This single property is what makes determinism (G1) and incrementality
(G5) achievable.

| Layer | Name | Models? | Emits |
| --- | --- | --- | --- |
| L0 | Ingest & normalize | none | `CanonicalDoc` (UTF-8 + offset map) |
| L1 | Deterministic structure | none | structural spine graph |
| L2 | Linguistic substrate | encoders | sentences, deps, coref, discourse |
| L3 | Encoder IE | encoders | typed mentions + relations |
| L4 | Optional LLM semantic | LLM (opt-in) | abstractions, WHY-nodes |
| L5 | Entity resolution | encoders | canonical nodes, `SAME_AS` lattice |
| L6 | Graph assembly | none | bi-temporal reified `Claim` graph |
| L7 | Analytics | none | communities, god nodes, bridges |
| L8 | Retrieval | encoders | ranked, cited context packs |
| L9 | Artifacts + surface | none | `graph.json` / `graph.html` / report / MCP |

Build order is strictly bottom-up: L0 → L1 → L2 → L3 → L5 → L6 → L7 → L8 → L9,
with L4 (the opt-in LLM pass) implemented last among the core layers, because
everything above it must work without it (`--no-llm` always produces a full graph).

## Foundation primitives (`textgraph/core/`) — implemented in Phase 0

| Primitive | Module | Serves |
| --- | --- | --- |
| Content addressing (`blake3`) | `content_address.py` | G3 provenance, G5 incremental cache |
| RLE offset maps | `offsets.py` | G3 — canonical char span → raw byte span |
| `CanonicalDoc` + normalization | `canonical_doc.py` | L0 contract for every later layer |
| Canonical JSON | `canonical_json.py` | G1 byte-stable artifacts |
| Pinned `Config` + hash | `config.py` | G1 — output is a function of config |
| `GraphStore` interface | `store/base.py` | backend-swappable L6/L7/L8 |

### Note: L1 confidence tag (source-doc discrepancy, resolved)

The research spec contradicts itself on the tag for structural-spine edges: §4.2
calls them `EXTRACTED`, while the §6.4 taxonomy defines `STRUCTURAL` as "read
directly from machine-readable structure, produced by L1." **§6.4 wins:** L1 edges
are `STRUCTURAL`. This is what the `ConfidenceTag` enum encodes and what Phase 1
must emit.

## Mission

TextGraph is aimed at **financial-crime and technical-crime investigation**:
turning heterogeneous case evidence into a graph that shows who/what connects to
whom, through what, and *why* — with audit-grade, re-verifiable provenance on every
claim. The `Rationale`/`Requirement` layer (the *why*) and byte-range provenance
(the *proof*) are the two features that matter most for this domain.

## Phase 1 (implemented): L0 + L1

- **L0 (`textgraph/l0_ingest/`)** — a format registry (`register`/`dispatch`)
  producing `IngestResult` = `CanonicalDoc` + span-carrying `Block` tree +
  hierarchical `Chunk`s. Built-in ingestors: markdown (markdown-it-py AST),
  plaintext, HTML/DOCX/ODT/RTF/EPUB (`richdocs`), JSON/YAML/TOML (`structured`),
  logs (template mining), transcripts. PDF is behind the `[ingest]` extra.
- **L1 (`textgraph/l1_structure/`)** — `parse_corpus` walks each block tree and
  inline text to emit the structural spine (sections, links, definitions,
  citations, cross-refs, fields, transcript threads, log templates, Rationale,
  Requirement). Every edge is `STRUCTURAL`, confidence 1.0, with a source span.
- **`GraphStore`** — in-memory backend with deterministic ordering; DuckDB/Parquet
  lands in Phase 4.
- **L9 (`textgraph/l9_artifacts/`)** — graph.json, GRAPH_REPORT.md, graph.html,
  schema.yaml, manifest.json.

## Phase 2 (implemented): L2 + L3

- **L2 (`textgraph/l2_linguistic/`)** — deterministic sentence segmentation,
  coreference-lite (pronoun/definite-NP → nearest compatible entity), and NegEx-style
  negation/modality. Statistical upgrades (spaCy, fastcoref, HeidelTime) attach
  behind the ``[ie]`` extra.
- **L3 (`textgraph/l3_encoder_ie/`)** — entity + relation extraction. The default
  backend (`rules`) is a deterministic, zero-model, CPU-only extractor: Organization/
  Person/Money/Account/Date/Email entities and TRANSFERRED/CONTROLS/DIRECTOR_OF/
  BENEFICIAL_OWNER_OF/ASSOCIATED_WITH relations, with predicate canonicalization
  (surface form kept as evidence). ``backend="gliner"`` selects the GLiNER encoder
  (``[ie]`` extra) with the same output shape.
- **Confidence taxonomy fully realised (G4).** L1 → `STRUCTURAL`; L3 entities/
  relations → `EXTRACTED`; coref-resolved relations → `INFERRED`; the (Phase-6) LLM
  pass → `GENERATED`. Every non-generated edge still carries a re-verifiable span.

## Phase 3 (implemented): L5

- **L5 (`textgraph/l5_entity_resolution/`)** — resolves alias entities to a canonical
  identity. Three stages, each with its own failure mode guarded:
  - **Blocking** (`blocking.py`) — deterministic keys (suffix-stripped name, acronym,
    first token), type-gated, unioned. Reduces the O(n²) cross-product while keeping
    recall ≥ 0.99 on true pairs.
  - **Scoring** (`scoring.py`) — suffix-stripped exact match, Jaro-Winkler, token-set,
    acronym↔name, plus the graph-native **relational** signal (shared neighbours).
  - **Clustering** (`clustering.py`) — **complete-linkage** agglomeration: two clusters
    merge only if *every* cross-pair clears the cohesion threshold, so one bad edge
    can't chain-merge dissimilar entities (the over-merge catastrophe).
- **Non-destructive** (§8.3): original entity nodes are kept; a new
  `("Entity","Canonical",<etype>)` node is linked to each member by a `SAME_AS` edge
  (tagged INFERRED, span-cited), so merges are auditable and reversible.
- `textgraph er audit` renders proposed merges for human review; B-cubed / blocking
  metrics (`metrics.py`) gate ER quality in CI. Splink is the optional `[er]` backend.
- Note: `"the company"` is resolved earlier by L2 coref; L5 handles the *entity-node*
  aliases (`Acme Corp` / `Acme Corporation` / `ACME`).

## Phase 4 (implemented): L6 + L7 + L8 + MCP

The graph becomes queryable. Every layer here is **pure-Python and deterministic** so
the analytics fold into a byte-identical `graph.json` (G1) and CI needs no GPU; the
heavy alternatives (Leiden, DuckDB, cross-encoder rerankers) are import-guarded
`[graph]` upgrades that fall back cleanly.

- **L6 — claim reification (`textgraph/l6_graph_model/claims.py`)** — each
  entity→entity relation edge is reified into a first-class `Claim` node carrying the
  full assertion (subject, predicate, object, confidence, polarity, modality) plus a
  temporal window. The direct edge is *kept*, so traversal is unchanged; the Claim is
  the thing `why` / `timeline` / `contradictions` point at and cite. `t_valid` is
  grounded to the nearest `Date` mention in the same sentence (byte proximity over the
  doc→Date `MENTIONS` spans); `t_invalid` is always null — **full bi-temporal
  invalidation is Phase 5**. No wall-clock ever enters the graph, and each reified
  `SUBJECT_OF` / `HAS_OBJECT` edge re-cites the relation's own byte span, so provenance
  still re-verifies (G3).
- **L6 (cont.) — bi-temporal assembly (`temporal.py`, Phase 5).** After reification,
  validity windows are closed across contradicting claims: for claims sharing a
  `(subject, predicate, object)`, the later-dated, opposite-polarity claim supersedes
  the earlier — the earlier's `t_invalid` is set to the later's `t_valid` and a cited
  `SUPERSEDES` edge is emitted (invalidation, not deletion). The ordering source is
  **valid-time dates stated in the text only** — no wall-clock — so an undated conflict
  is left open (surfaced via L7 `CONTRADICTS`) rather than ordered by a guess, and
  `graph.json` stays byte-identical (G1).
- **L7 — analytics (`textgraph/l7_analytics/`)** — over a weighted entity subgraph
  (edge weight `confidence · log(1+evidence_count)`): weighted **PageRank** and
  **Brandes betweenness** (`algorithms.py`), **label-propagation communities** with
  automatic **c-TF-IDF labels** (`communities.py`), and the diagnostics an investigator
  reads first (`analyze.py`): **god nodes** (top on *both* centralities — a hub that is
  also a bottleneck), **bridges** (inter-community edges whose removal disconnects),
  orphans, and **contradictions** (same triple, opposite polarity). `enrich.py` folds
  the findings back into the graph: centrality/community become entity-node properties
  and each contradiction becomes a `CONTRADICTS` edge between the two `Claim` nodes.
  Centrality floats are rounded to fixed precision before serialization to keep the
  byte-identical gate safe.
- **L8 — retrieval (`textgraph/l8_retrieval/`)** — the **dual-node graph**
  (`emit_chunks.py`) materialises `Chunk` passage nodes carrying their text, linked
  `doc -[HAS_CHUNK]-> chunk` and `chunk -[MENTIONS]-> entity` (by byte-containment of
  the mention span in the chunk), so a lexical hit teleports PageRank onto the right
  entities. `QueryEngine` (`engine.py`) exposes **eight typed tools**: `search`
  (BM25 in `bm25.py` fused with **Personalized PageRank** by **Reciprocal Rank Fusion**,
  with local/global routing), `neighbors`, `path` (**maximum-likelihood** — Yen's
  k-shortest under `-log(confidence)` weights), `why`, `timeline`, `contradictions`,
  `communities`, `stats`. Every result is a **bounded, cited context pack** from
  `model.py`: token-budgeted (G7), each row carrying a `[doc:start-end]` byte citation
  (G3) — an agent never sees raw Cypher (G6).
- **MCP surface (`textgraph/mcp/`)** — `tools.py` is the single source of truth for the
  tool specs *and* the dispatcher (no `mcp` dependency, fully CI-tested); `server.py` is
  the thin stdio adapter behind the `[mcp]` extra. The CLI (`textgraph query|path|
  explain`) is a second formatter over the *same* `QueryEngine` — never a drifting code
  path (§6.4).
- **Benchmark (`benchmarks/retrieval.py`, `BENCHMARKS.md`)** — recall@k and MRR reported
  *with* their cost (tokens/query, p50/p95 latency): "no number without its cost" (G7).
  The fixture set runs with zero downloads; LoCoMo / LongMemEval-S run only when their
  data is present locally, so CI never fetches a corpus.

## Phase 5 (implemented): storage + incrementality

- **Persistent store (`store/duckdb_store.py`, `[graph]`/`[er]` extra).** A
  `DuckDBGraphStore` implements the `GraphStore` ABC over a DuckDB file — labels/
  properties/spans as JSON, the confidence tag as its enum value — so the round-trip is
  exact and a graph **reloads from disk without re-running the pipeline**. Import-guarded
  (raises `UnsupportedFormat`, never a hard failure in the lean install). `textgraph
  build --store g.duckdb` persists; any query verb given a `.duckdb` path loads it.
- **Incremental rebuild (`core/incremental.py`, G5).** The expensive layer (per-document
  IE) is a pure function of `(doc bytes, config)`, so its emitted nodes/edges are cached
  keyed by `(doc_id, config_hash)` — and `doc_id` *is* the blake3 of the bytes, so an
  edit changes the key and only that file is re-extracted. The cross-document layers
  (L5–L8) always re-run; the result is **byte-identical** to a full build (verified in
  CI). `build(root, cache_dir=…)` opts in.
- **`textgraph watch <dir>` (`watch.py`).** Content-addressed change detection (blake3,
  not mtime) triggers an incremental rebuild + artifact re-write on every edit. It
  refuses an output/cache dir nested inside the watched corpus, which would otherwise
  re-ingest its own `graph.json`/`.md`/`.html` and loop.

## Phase 6 (in progress): the optional LLM pass (L4)

- **L4 is the one non-deterministic layer, and it is quarantined.** Off by default (G2)
  so the determinism gate never sees it; when enabled with `build --llm` it runs *last*
  (over finished communities) and every node/edge it emits is tagged **`GENERATED`** (G4)
  — model-authored content that can never be mistaken for an extracted, cited fact and is
  exempt from provenance re-verification. `graph.json` stays byte-identical whenever the
  LLM is off.
- **Grounded synthesis (`l4_llm_optional/synthesize.py`).** For the largest L7
  communities it sends the LLM *only* the member entities + the relations among them and
  asks for a 1-2 sentence summary, emitting a `Summary` node + `SUMMARIZES` edges to the
  most central members. Hard-budgeted (`llm_max_calls`, biggest communities first, G7).
- **Reproducibility despite non-determinism (`cache.py`).** Responses are cached by a
  content hash of `(model, system, user, params)`, so a warm `--llm` rebuild re-emits the
  same summaries for free — the same prompt never costs a second call.
- **Secret hygiene (`client.py`).** A dependency-free, OpenAI-compatible client (stdlib
  `urllib`) points at any `/chat/completions` endpoint via `base_url`. The API key is read
  from the environment only (`API_KEY` / `TEXTGRAPH_LLM_API_KEY` / `OPENAI_API_KEY`); it
  never touches `Config`, `config_hash`, or any artifact. An unconfigured `--llm` build
  skips L4 rather than failing.

- **Local console (`textgraph/console/`).** `textgraph console` serves a dependency-free,
  read-only web UI over the same `QueryEngine` + `call_tool` dispatcher the CLI and MCP
  server use (G6 — one query surface, many formatters). Built on stdlib `http.server`;
  the page is self-contained (inline CSS/JS, no CDN, G2). The request→response logic is a
  pure `route()` function, so the whole API is unit-tested without binding a socket.

## Phase 7 (implemented): GQL / ISO-GQL standards layer (`textgraph/gql/`)

- **Why.** A knowledge graph that speaks only its own API is a silo. ISO/IEC 39075 (GQL)
  is the standard declarative language for property graphs; exposing a GQL surface lets any
  enterprise agent query TextGraph the way it queries Neo4j / Memgraph / Kùzu, so the cited
  context packs are portable across backends.
- **What.** A pure-Python, deterministic GQL/Cypher *subset*: a `tokenizer` → recursive-descent
  `parser` → AST → `GQLEngine` executor that runs against the **same** `(nodes, edges)` the L8
  `QueryEngine` holds. It **only reads** the graph, so G1/G2/G3 are untouched and byte-stable
  `graph.json` is unaffected; every result row is stably ordered (deterministic), and
  provenance (`source_spans`) stays reachable through edge properties.
- **Coverage.** Node patterns with labels + property maps; relationships in every direction
  (`->`, `<-`, `-`); **quantified/variable-length paths** `-[:T*min..max]->` (the ISO-GQL
  feature that expresses multi-hop reachability) — loop-free and depth-capped so they always
  terminate (G7); `WHERE` (`= <> < <= > >= CONTAINS STARTS WITH ENDS WITH IN`, `AND`/`OR`/`NOT`);
  `RETURN` with `type()`/`labels()`/`id()`, `count(*)` aggregation, `AS`, `DISTINCT`, `ORDER BY`,
  `SKIP`, `LIMIT`.
- **One graph, two surfaces.** The typed L8 tools and the GQL engine read a single property
  graph — the pattern-based tools (`neighbors`, `path`, `contradictions`) round-trip to
  equivalent GQL, proving the surface is faithful. Hybrid `search` (BM25+PPR) and aggregate
  `why` stay tool-only by design — they aren't graph *patterns*.

## Phase 8 (implemented): vision-native late-interaction retrieval (`l8_retrieval/vision/`)

- **Why.** OCR-then-chunk loses layout, tables, stamps, and figures. State-of-the-art
  visual retrieval (ColPali / ColQwen2 / ColFlor) instead embeds *rendered page images*
  into multi-vector patch representations and scores them against the query with **MaxSim**
  late interaction — no text serialization. TextGraph adds that retrieval channel.
- **The operator (`maxsim.py`).** A query and a page are each a `MultiVector`; relevance is
  `sum_i max_j (q_i . p_j)` — each query token aligned to its best page patch. This module
  only ever sees vectors, so it is pure-Python, deterministic (G1), and unit-tested with no
  GPU.
- **Embedders (`embed.py`), upgrade-or-fall-back.** The default `hash` embedder maps each
  token to a fixed unit vector (SHAKE-256, stdlib) — semantics-free but enough to run and
  test the *whole* late-interaction pipeline reproducibly (G1/G2). `vision_backend='colpali'`
  loads a real model over page images behind the **`[vision]`** extra; if it's absent,
  `resolve_embedder` falls back to `hash` (same pattern as GLiNER/Splink/Leiden).
- **Retriever (`retriever.py`) + engine.** `VisionRetriever` embeds each *document-as-page*
  once and MaxSim-ranks them; `QueryEngine.vision_search()` exposes it, and `textgraph vision`
  is the CLI. Crucially, **embeddings are computed at query time only** — pages are the
  documents that already seed PageRank through their entity mentions — so `graph.json` is
  byte-identical and the default install is untouched. The `[vision]` model is where
  image-native gains land; the deterministic default proves the plumbing, benchmarked in
  `BENCHMARKS.md`.

## Phase 9 (implemented): enterprise fine-grained access control (`textgraph/security/`)

- **Why.** Unrestricted graph algorithms — PPR, community detection, multi-hop paths —
  will happily traverse restricted nodes and synthesize context packs from documents the
  requester may not read (gap-analysis §3, "context-bleeding"). Enterprise use needs
  authorization enforced *inside* the engine, at every traversal step, not as a
  post-filter.
- **Two models (`rebac.py`, `abac.py`).** ReBAC is a small deterministic Zanzibar/OpenFGA:
  relation tuples `object#relation@subject` with `owner`/`viewer`/`member`/`parent` and
  userset rewrites, so access flows along transitive policy paths (user → group → folder →
  document). ABAC adds Cedar-style attribute conditions (`MinClearance`, `IpAllowlist`,
  `TimeWindow`) evaluated against a resource's own attributes. Both are pure-Python,
  sorted-iteration, depth-bounded — deterministic and terminating on cyclic policies (G1/G7).
- **Document-level policy (`policy.py`).** Every node/edge is provenance-linked to its
  source documents, so authorization is decided per document (ReBAC **and** ABAC), then
  lifted to nodes: a node is visible iff its provenance touches an authorized document; a
  node with no known provenance is denied (secure default).
- **Security-aware traversal (in `l8_retrieval/engine.py`).** Attach a `SecurityPolicy`;
  pass a `SecurityContext` per call. `search` runs PPR on a graph **masked** to authorized
  nodes — every edge into an unauthorized node is dropped, so its transition probability is
  literally `0` (§3.2), and it can neither seed nor be reached by the walk. `path` prunes
  restricted nodes and edges inside Dijkstra/Yen; `neighbors`/`why`/`timeline`/
  `contradictions`/`communities`/`vision_search` all filter to authorized content, and an
  edge is hidden unless its *own* attesting document is authorized. **With no policy or no
  context, every method is byte-identical to the un-secured engine** — access control is
  query-time only, so `graph.json` and the default install are untouched (G1/G2).
- **Upgrade-or-fall-back + proof.** `RebacStore` is the dependency-free default; a real
  OpenFGA service is opt-in behind **`[security]`** (`resolve_policy_engine`, import-guarded).
  `textgraph secure … --policy p.json --principal alice` is the CLI. A red-team suite
  (`tests/integration/test_security_redteam.py`) proves **zero context-bleed** through
  PPR/paths/summaries/vision — and that the leak is real without a policy — while
  `benchmarks/security.py` measures the overhead (~+14% p50).

## Phase 10 (implemented): Graph-of-Thoughts agent reasoning (`textgraph/got/`)

- **Why.** A static knowledge graph is domain *memory*; agentic problem-solving also needs
  a *cognitive* structure. Chain- and Tree-of-Thought are linear/branching; the
  Graph-of-Thoughts framework (gap-analysis §4) generalises reasoning to an arbitrary graph
  of thought vertices with backtracking, aggregation, and refinement — and, crucially
  (ESCARGOT), grounds every thought in retrieved KG evidence to fight hallucination.
- **The model (`thought.py`).** A GoT process is a tuple of thought vertices `V`, dependency
  edges `E`, a role function `sigma` (Plan / SubProblem / Hypothesis / VerificationStep /
  DistilledSummary), and four operators. `Thought`/`ThoughtGraph` implement exactly that,
  with one invariant: a *substantive* thought must carry real `[doc:span]` evidence, or it
  is not grounded and gets pruned.
- **The reasoner (`reason.py`).** `reason(query)` runs the four operators over the real
  tools an agent would call: **Generation** = `neighbors` of a focus entity, **Aggregation**
  = a `path` connecting two focuses, **Refinement** = `why` claims + a `gql` triple check,
  **Distillation** = score, prune, and summarise under a token/tool budget. Each operator
  binds its tool result's citations onto the thought it creates, so the trace is verifiable
  end to end (G3).
- **Adaptive, not static (DGoT/AGoT).** Complexity — how many entities the *query* names —
  is measured at runtime. A single-entity question runs a cheap linear chain; only when
  complexity crosses a threshold does the loop spawn the (expensive) Aggregation/Refinement
  branches. A `static` mode expands the full topology regardless, so `benchmarks/reasoning.py`
  can show the adaptive path is ~70% cheaper at equal grounding. `textgraph reason` is the
  CLI. Deterministic and read-only — `graph.json` is untouched (G1).

### Why the default backend is model-free

Determinism (G1) must survive in CI, which can't download model weights, and the
tool must run with zero GPU (G2). So the *default* extractor is deterministic rules;
GLiNER is the higher-recall opt-in. Both emit the same `IEResult`, so the graph
shape, provenance, and downstream layers are backend-independent. When the GLiNER
path is used, weights are pinned and inference is temperature-free to preserve G1.

### Provenance model

A citation stores a **canonical character span**. Verification maps it back to a
**raw byte span** through the doc's offset map and re-hashes the source bytes; a
citation is valid iff the re-hash matches the stored hash.

Two ingestion modes preserve this guarantee:

- **Byte-preserving** (md, txt, logs, json/yaml/toml, transcripts): canonical text
  derives from the raw file bytes, so citations point at the **original file**.
- **Derived-text** (docx, pdf, odt, epub, rtf, html): the extracted plain text
  can't be a byte-substring of the binary, so the **extracted text becomes the
  canonical document** (`doc_id` content-addresses it) and spans re-verify against
  it. Investigators still get an exact, re-hashable citation into normalized text.

Normalization (CRLF→LF, BOM stripping, multi-byte UTF-8, and undecodable bytes via
`surrogateescape`) never breaks the mapping — the offset map records exactly how
many raw bytes each canonical character consumed.

## Design goals

See [README.md](README.md#design-goals-non-negotiable) for G1–G9. When goals
conflict, the lower-numbered one wins unless a phase's Definition of Done says
otherwise.

## Storage

NetworkX in-memory for compute + DuckDB/Parquet on disk as the source of truth,
both behind the `GraphStore` interface so a GQL-native engine can be swapped in
(Phase 7) without touching L6/L7/L8 call sites.
