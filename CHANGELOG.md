# Changelog

All notable changes to TextGraph are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to Semantic Versioning.

## [Unreleased]

## [3.3.0] - 2026-08-08

**Semantic-web interop — closing the RDF / ontology gap with polyglot peers.** New
deterministic, dependency-free exports so the graph loads into any triple store and
validates in any semantic-web toolchain.

### Added
- **RDF/Turtle export** — `textgraph export --format rdf` emits the whole graph as Turtle
  (loads into Oxigraph / Apache Jena / RDF4J / any SPARQL store): nodes typed by their
  labels, relations as `tgr:` predicates, and **every cited edge reified as an
  `rdf:Statement`** carrying the `ConfidenceTag` + the re-verifiable byte span
  (`prov:wasDerivedFrom`, `tgo:sourceStart/End/Hash`) — provenance survives the round-trip
  (G3). Validated with rdflib; pure-string, no RDF dependency.
- **OWL vocabulary export** — `--format owl` emits `owl:Class` per node label,
  `owl:ObjectProperty` per relation predicate (with induced `rdfs:domain`/`range`), and
  `owl:DatatypeProperty` per scalar key.
- **SHACL shapes export** — `--format shacl` emits a `sh:NodeShape` per class with
  constraints (label cardinality, per-predicate `sh:class`) **induced from the actual data**
  — validate the graph in pySHACL / TopBraid / Jena.

All four export formats (`rdf`, `owl`, `shacl`, `prov-o`) are byte-deterministic (G1).

## [3.2.1] - 2026-08-08

**Packaging & presentation polish** (no code/API changes). Makes the PyPI page and repo
look the part next to [Semantica](docs/COMPARISON_SEMANTICA.md).

### Added
- **`LICENSE`** file (MIT) — so the license is detectable on GitHub and shipped in the sdist.
- **PyPI project metadata** — `[project.urls]` (Homepage / Repository / Documentation /
  Changelog / Live demo / Bug Tracker → the PyPI sidebar) and trove `classifiers` (Python
  versions, MIT, audiences, topics), plus `license-files`.
- **README** — a compact **TextGraph vs. Semantica** section (where TextGraph leads: byte-
  identical builds, re-hashable citations, zero-LLM core; and the honest roadmap: RDF store,
  OWL/SHACL, more providers/vector stores). A **Python-API** quick start alongside the CLI.

### Fixed
- **Broken README badges** — the CI badge pointed at a non-existent `ci.yml`; replaced with
  working **tests** + **determinism** workflow badges and an MIT license badge.

## [3.2.0] - 2026-08-08

**TextGraph 3.2 — LLM-augmented intelligence, without losing the moat.** Adds semantic
retrieval and opt-in LLM assistance for both **input** (extraction) and **output** (answers),
benchmarked against [Semantica](docs/COMPARISON_SEMANTICA.md). Every addition is **opt-in and
quarantined** — the deterministic-by-default build (byte-identical `graph.json`), byte-level
provenance, and zero-LLM default are all untouched.

> **Note:** the PyPI distribution is now **`textgraph-kg`** (`pip install textgraph-kg`); the
> import package and CLI remain `textgraph`. (`textgraph` was already taken on PyPI.)

### Added
- **Dense semantic retrieval.** A third, *semantic* signal fused into the existing BM25 +
  Personalized-PageRank RRF blend. Backends behind one interface: `openai` (OpenAI-compatible
  `/embeddings` — local **Ollama `nomic-embed-text`**, vLLM, or OpenAI, dependency-free), `st`
  (local `sentence-transformers`, `[embed]` extra), and `hash` (deterministic, model-free). A
  persistent disk cache means only cache-misses hit the model. **Query-time only — never enters
  `graph.json`**, so determinism (G1) is unaffected. `textgraph query … --embed openai`.
- **LLM relation extraction (input).** `build --llm-extract` runs the LLM (default: NVIDIA
  **Nemotron** via vLLM, `client.DEFAULT_LLM_MODEL`) over chunks to add `GENERATED`-tagged
  relations the deterministic extractors miss — each cited to its chunk, bounded by a call
  budget (G7), prompt-cached. Off by default, so the default build has zero `GENERATED` edges
  and the determinism/provenance gates are untouched.
- **LLM answer synthesis (output).** `query --narrate` composes a fluent, **cited** answer
  strictly from the retrieved evidence — tagged `GENERATED`, instructed to abstain when the
  evidence is insufficient, and always shown next to its re-verifiable citations.
- **`docs/COMPARISON_SEMANTICA.md`** — an honest TextGraph-vs-Semantica comparison.

## [3.1.0] - 2026-08-08

**TextGraph 3.1 — the decision-provenance & conflict release.** On top of v3.0's interactive
surface, 3.1 makes the graph *accountable*: it models **decisions** as a first-class causal
layer, detects and (optionally) resolves **conflicting claims** without ever silently merging
them, exports an interoperable **PROV-O** audit trail, and adds a first-run **doctor**. All of
it preserves the moat: **deterministic build (byte-identical `graph.json`), byte-level
provenance, zero-LLM-by-default, local-first.**

Highlights:
- **Decision objects + causal chains** — `WHY`/`DECISION`/`RATIONALE`/`ADR-N` become
  `Decision` nodes with `CAUSED`/`INFLUENCED`/`PRECEDENT_FOR` edges; `trace-decision` walks a
  decision's lineage (what led to it, what it led to) and `find-decisions` searches them —
  all cited.
- **Conflict detection & resolution** — single-truth disagreements are surfaced as
  `Conflict` nodes (never a silent merge); opt-in `most_recent`/`voting`/`credibility_weighted`
  resolution demotes losers non-destructively (`SUPERSEDED_BY`, keeping citations).
- **PROV-O export** — `textgraph export --format prov-o` emits a W3C PROV-O JSON-LD trail.
- **`textgraph doctor`** — read-only environment + on-machine determinism health check.
- **Console** — a `graph.json` "Save snapshot" export, and the Ask chat now routes to the
  conflicts / trace / find-decisions tools with inline cited detail.

### Added
- **Console "Ask" chat routes to the decision/conflict tools.** Natural-language questions
  now reach `conflicts`, `trace` (decision chain), and `find-decisions`: "are there
  conflicts", "what led to this decision", "find decisions about retention". The chat renders
  the causal chain and conflict list inline (relation, direction, resolution) with citation
  chips, and new tool chips are selectable directly. `"conflict"` and `"contradiction"` now
  route to their distinct tools. Tracing a body decision promotes to its ADR record so the
  full lineage always surfaces.
- **Decision-chain traversal + similarity (`trace_decision_chain`, `find_similar_decisions`).**
  `QueryEngine.trace_decision_chain(decision)` walks a decision's causal lineage — backward
  over `CAUSED`/`INFLUENCED`/`PRECEDENT_FOR` for **what led to it** (precedents/causes) and
  forward for **what it led to** (effects) — as ordered, cited, cycle-safe, depth-bounded
  hops. `QueryEngine.find_similar_decisions(query)` ranks `Decision` nodes by BM25 relevance
  of their statement text, each hit cited to its source span. New `textgraph trace-decision`
  and `textgraph find-decisions` CLI verbs; both are security-aware (a decision whose source
  is unauthorized never surfaces). Causal linking now attributes an in-body ADR reference to
  the document's ADR record, so ADR-level lineage stays connected end to end.
- **Conflict detection (truth discovery) — a first-class step, never a silent merge.**
  When two sources make incompatible claims about the same entity on a *single-truth*
  predicate (`CONTROLS`, `BENEFICIAL_OWNER_OF`, `DIRECTOR_OF` by default) — same subject
  (after `SAME_AS`), different objects, **overlapping validity windows** — TextGraph now
  surfaces a first-class `Conflict` node (severity-tagged) with cited `CONTENDS` edges to
  every contending claim. Detection is deterministic and **only surfaces** the conflict;
  it never picks a winner or deletes a claim (G3). The bi-temporal check means a legitimate
  sequential change (director of Beta in 2019, of Gamma in 2021) is *not* flagged, while
  genuinely contemporaneous claims are. New `textgraph conflicts` CLI verb,
  `QueryEngine.conflicts()`, a **Conflicts** section in `GRAPH_REPORT.md`, and
  `Config.detect_conflicts` / `Config.single_truth_predicates`.
- **Conflict resolution (opt-in, pluggable, never destructive).** With
  `build --resolve-conflicts <strategy>` (or `conflicts --resolve <strategy>`), TextGraph
  picks a winning object per conflict and **demotes** the losing claims — they gain
  `superseded_by` / `resolved_by` properties and a cited `SUPERSEDED_BY` edge to the
  winner, but are **never deleted** (G3). Three deterministic strategies: `most_recent`
  (latest in-text validity date; undated ⇒ honestly left unresolved), `voting` (most
  distinct sources, ties broken by earliest source), and `credibility_weighted` (summed
  per-source `Config.source_credibility`, defaulting to 1.0 so it degrades to voting).
  `SUPERSEDED` is an orthogonal marker, **not** a fifth `ConfidenceTag` tier — the four-tier
  taxonomy and the provenance gate are untouched. Resolution is config-pinned, so
  `graph.json` stays byte-identical.
- **Decision objects — a queryable causal layer over `Rationale`.** Decision-worthy L1
  markers (`WHY`/`DECISION`/`RATIONALE`/`ADR-N`) are promoted into first-class `Decision`
  nodes (category, statement, byte-span citation), each linked back to its rationale via a
  cited `DERIVED_FROM` edge. Author-controlled **causal edges** — the narrow, agent-legible
  trio `CAUSED` / `INFLUENCED` / `PRECEDENT_FOR` — are inferred from explicit in-text ADR
  references (e.g. `DECISION: … SUPERSEDES ADR-0007`). Deterministic, cited, and default-on;
  disable with `Config(derive_decisions=False)`. (Automated `trace_decision_chain` /
  `find_similar_decisions` remain future work — they depend on L6/L8.)
- **PROV-O export** — `textgraph export --format prov-o` emits a W3C PROV-O **JSON-LD**
  decision-provenance trail: `Decision → prov:Activity`, source `Document → prov:Entity`
  (`prov:used`), the extractor → `prov:SoftwareAgent` (`prov:wasAssociatedWith`), and the
  causal edges → `prov:wasInformedBy` (effect informed by cause). Byte-range citations ride
  along as `textgraph:sourceSpan`. Dependency-free and byte-stable.
- **`textgraph doctor`** — a read-only environment health check for first-time triage.
  Checks Python version, temp-dir writability, core/optional extras (`[ingest]`, `[ie]`,
  `[er]`, `[graph]`, DuckDB), and — the marquee check — **on-machine determinism**: it
  builds a tiny corpus twice and asserts a byte-identical `graph.json`, confirming the
  exact guarantee CI enforces. Human-readable by default; `--json` for CI preflight gates;
  `--check <name>` runs one named check in isolation. No `--fix` (read-only by design).
- **Console graph.json export** — a read-only "Save snapshot" button in the console
  downloads a canonical `graph.json` of the current graph (reflecting any in-UI ingest).
  A corpus-directory console rebuilds from source for a complete artifact (with the `docs`
  manifest); a `.duckdb`/snapshot console serializes the live engine's nodes + edges via
  `export_graph_bytes`. Served at `GET /api/export`; deterministic and byte-canonical.
  Hidden on the offline `graph.html` (no server).

## [3.0.0] - 2026-08-06

**TextGraph 3.0 — the interactive + investigator-defaults release.** On top of the v2.0.0
enterprise extensions, 3.0 adds a grounded conversational surface and acts on a competitive
market review — making the highest-leverage capabilities the *default*, proving quality
honestly, and hardening for real use. All of it preserves the moat: **deterministic build
(byte-identical `graph.json`), byte-level provenance, zero-LLM-by-default, local-first**.

Highlights:
- **Console "Ask" chat** — ask in plain English; routed to the right graph tool, answered
  **cited**, with the answer highlighted on the graph, a collapsible reasoning chain,
  multi-turn follow-ups, **grounding confidence + abstention**, and opt-in **file-attach
  ingestion** into the live graph. Plus a redesigned, spacious, theme-aware UI.
- **Investigator defaults** — **PDF text ingestion is now built-in** (pypdf → core), entity
  resolution confirmed on-by-default, and the `[ie]` GLiNER backend runs **int8-quantized
  ONNX** for usable CPU speed.
- **Retrieval & integrations** — documented query routing, **LangChain / LlamaIndex adapters**
  that keep byte-span citations, and a Neo4j scale-out **design** (DuckDB stays default).
- **Proof & honesty** — an extraction-quality benchmark that **publishes the hallucinated-edge
  rate (0.167)** and an honest peer comparison; grounding/abstention ("insufficient evidence").
- **Ops hardening** — a provenance/SAME_AS/invalidation **admin inspector**, incremental
  reindex stress + partial-write recovery, and optional console **token auth** + ingest lock.

Breaking-ish: `pypdf` is now a core dependency (installs by default). Full per-item detail
below.

### Changed — positioning leads with the differentiators (Sprint 4.4)
- **README** now opens with a **"Why it's different (vs GraphRAG)"** section that leads with
  the real edge — *deterministic* (byte-identical `graph.json`), *byte-level provenance* (100%
  re-verified), *zero-LLM-by-default*, *bi-temporal versioning*, and a *published
  hallucination rate* — instead of generic "GraphRAG" framing, and states plainly that
  local-first/DuckDB is the default with Neo4j only an optional scale-out backend. These are
  the axes the market scan found TextGraph actually wins on and had been under-selling.

### Hardened — console server concurrency + optional auth (Sprint 4.3)
- **Ingest serialization:** the file-attach rebuild + engine hot-swap is now guarded by a
  lock, so two concurrent uploads can't race. Reads stay lock-free (an engine swap is a
  single atomic reference assignment under the GIL — a reader sees the old or new engine,
  never a torn one); the concurrency model is documented on `_State`.
- **Optional bearer-token auth:** `textgraph console … --token <T>` requires the token on
  `/api/*` (via `Authorization: Bearer` or `?token=`) while still serving the page — recommended
  before binding a non-localhost `--host`. Verified live (401 without, 200 with). *Flagged as
  future:* async indexing jobs and full multi-user identity are out of scope for this pass
  (they would need a job queue / user store); the token is basic per-instance auth.

### Added — graph inspection / provenance admin view (Sprint 4.1)
- **`QueryEngine.inspect(node)` + `GET /api/inspect`** — the "admin console" detail most
  GraphRAG tools lack: for any node, its re-verifiable **provenance** spans, the **confidence
  tier** histogram of its relations (`EXTRACTED`/`INFERRED`/…), its non-destructive
  **SAME_AS** cluster (canonical + members), and each claim's **validity window /
  supersession** history. Access-controlled like the other tools. The console inspector now
  renders these sections when a node is clicked; the offline `graph.html` falls back to
  `why()` gracefully. +1 test.

### Hardened — incremental reindex stress + partial-write recovery (Sprint 4.2)
- **`DocIECache.get()` now recovers from a corrupt / partially-written cache entry** (a crash
  mid-write leaving truncated JSON): it's treated as a miss, the poisoned file is dropped, and
  the document is re-extracted — a bad cache never fails a build (G5). +4 stress tests: after
  deleting or modifying a document, an incremental rebuild is **byte-identical** to a clean
  full rebuild; a poisoned cache recovers to the identical graph.

### Added — extraction-quality benchmark + honest peer comparison (Sprint 3.1 / 3.2)
- **`benchmarks/quality.py`** — measures the extracted graph against a hand-labelled gold set
  on the `docs` fixture: entity P/R/F1 (**1.0/1.0/1.0**), asserted-relation P/R/F1
  (**0.833**), **false / hallucinated edge rate (0.167 — reported, not hidden)**, and
  **citation coverage (1.0)**. It credits the extractor for correctly tagging *negated*
  relations (`polarity=neg`) and names its one honest weakness (a coreference error). Gated
  by `tests/integration/test_quality_benchmark.py` so quality can't silently regress.
- **`BENCHMARKS.md`** gains the quality numbers and an **honest peer comparison** vs Graphiti
  / LightRAG / HippoRAG / Neo4j GraphRAG Python: a *capability* table on the axes that differ
  (byte-level provenance, deterministic build, zero-LLM-default, measured hallucination rate,
  bi-temporal versioning), with an explicit statement that a fair *head-to-head QA* comparison
  isn't feasible yet (peers are LLM-driven/non-deterministic) — no fabricated numbers.

### Added — answer-grounding confidence + abstention (Sprint 3.3)
- **`textgraph/l8_retrieval/grounding.py`** — the "Ask" chat now scores how well each answer
  is supported by citation evidence and **abstains** ("Insufficient evidence in the graph to
  answer that confidently.") instead of surfacing an unsupported guess. Deterministic and
  pure: non-factual aggregates (stats/communities/contradictions/gql) are always confident;
  factual answers (search/why/path/neighbors/timeline/reason) with **zero citations** abstain,
  and confidence rises with the number of distinct cited spans. `ChatAnswer` gains
  `confidence` + `abstained`, surfaced in the UI as a "N% grounded" / "abstained" badge. +4 tests.
- *Audit note:* the retrieval PPR is **already query-conditioned** — `search` personalizes the
  PageRank teleport from the query's named entities + top lexical chunks (`personalization=seed`
  in `l7_analytics.algorithms.pagerank`), so a query-specific walk was in place since Phase 4;
  Sprint 3.3's new contribution is the grounding/abstention layer on top.

### Added — LangChain / LlamaIndex adapters, citations preserved (Sprint 2.5)
- **`textgraph/integrations/`** — consume the TextGraph graph from LangChain and LlamaIndex
  **without dropping byte-span provenance**. Pure converters (`search_to_documents`,
  `search_to_nodes`) map a `SearchResult` to `Document`/`TextNode`-shaped payloads that carry
  every `[doc:start-end]` citation in `metadata` (G3 preserved). Framework retriever classes
  (`make_langchain_retriever`, `make_llamaindex_retriever`) subclass each framework's
  `BaseRetriever`, import-guarded behind the new `[langchain]` / `[llamaindex]` extras (clear
  `UnsupportedFormat` without them). +4 tests (converters + citation preservation + fallback).
- **G3 verified, not assumed:** both `Document.metadata` and `TextNode.metadata` are free-form,
  so neither framework forces dropping citations — the adapters ship. Flagged in the module:
  if a framework required opaque metadata-less chunks, that would violate G3 and we would not
  ship its adapter.

### Design — optional Neo4j scale-out backend (Sprint 2.4, `docs/plans/neo4j-backend.md`)
- Design (no code) for an **opt-in** `textgraph serve --backend neo4j` that *materializes an
  already-built `graph.json`* into Neo4j for scale — the DB is a downstream query target,
  never the source of truth or part of the deterministic build, so G1/G2/G3 are preserved and
  **DuckDB stays the default**. Compared feature-by-feature against Neo4j GraphRAG Python
  (VectorCypherRetriever, ToolsRetriever, GraphPruner, EntityResolver, schema-guided
  extraction, lexical graph, Cypher 25 `SEARCH`): adopt the retrieval-shape patterns; reject
  as *defaults* the ones that push LLMs/non-determinism into the build. Recommends building a
  read-only Neo4j loader/query backend behind `[neo4j]` first.

### Added — documented per-query retrieval routing (Sprint 2.2)
- **`textgraph/l8_retrieval/routing.py`** — one deterministic, ordered rule set that maps a
  question to a retrieval *tool* (`classify_query`) and a *strategy family*
  (`route` → `RoutePlan{tool, strategy, reason}`): structured-graph (GQL), graph-traversal
  (path/neighbors/why/timeline), graph-analytics (communities/contradictions/stats),
  hybrid-lexical-graph (`search` = BM25 + Personalized PageRank + RRF), hybrid-multi-tool
  (`reason` = Graph-of-Thoughts). The console "Ask" chat now shares this single source of
  truth (its inline `classify` was promoted here), so routing can't drift between surfaces.
  Rules documented in `docs/retrieval-routing.md`; the `reason` string is surfaced for
  auditability (G6). +4 tests.
- *Audit note:* Sprint 2.1 (L6 bi-temporal Claims, L7 analytics — communities/god-nodes/
  bridges/contradictions, L8 hybrid BM25+PPR+RRF with local/global routing) and Sprint 2.3
  (multi-hop max-likelihood **k-shortest path ranking**, Yen's algorithm, every step cited)
  shipped in Phases 4–10 and are covered by existing tests — confirmed complete, not re-done.

### Changed — PDF ingestion is now a default capability (Sprint 1.1)
- **`pypdf` moved from the `[ingest]` extra into the core dependencies**, so `textgraph build`
  ingests PDF text out of the box — investigators live in PDFs, and gating that behind an
  extra was an adoption barrier. `pypdf` is pure-Python, BSD-3 licensed, small, and
  deterministic (no binary deps, no GPU), so it doesn't compromise the lean, local-first
  default (G2) or determinism (G1). Higher-fidelity **layout / table / OCR** extraction
  (Docling) stays opt-in in `[ingest]`. `requirements.txt` gains `pypdf`; README "Supported
  formats" updated. +1 test (`test_pdf_ingests_by_default`, a self-contained minimal PDF).

### Changed — GLiNER backend runs int8-quantized ONNX on CPU (Sprint 1.3)
- **The `[ie]` GLiNER backend now loads the int8-quantized ONNX model by default** (new
  `Config.ie_onnx=True`), the well-known fix for GLiNER's punishing CPU latency (minutes per
  handful of chunks on the fp32 torch path). `load_model()` prefers `onnx/model_quantized.onnx`
  and falls back to the torch weights if that file isn't published for the pinned model — so
  higher-recall extraction is finally usable without a GPU.
- **Wired the backend properly** (it was a stub): GLiNER now supplies the NER *mentions*, and
  relations are built by the **same deterministic extractor the rule backend uses** — the
  relation/coref/predicate logic was factored into a shared `assemble_ie()` (byte-identical to
  before; the determinism gate proves it). So recall goes up with **no new nondeterminism**,
  and the `IEResult` shape is unchanged.
- CI honesty: `[ie]` + a downloaded model aren't in the lean CI, so the model-load/NER lines
  are `# pragma: no cover` and must be validated on a machine with the extra; the pure pieces
  (prediction→mention mapping, availability, fallback) are unit-tested. +3 tests. The default
  **rules** backend and the byte-identical `graph.json` are untouched.

### Confirmed — entity resolution is on by default (Sprint 1.2)
- **L5 entity resolution already runs in every `build()`** with the deterministic **rules**
  backend (`Config.resolve_entities=True`, `er_backend="rules"`) — no extra, no flag —
  collapsing aliases (`Acme Corp` / `Acme Corporation` / `ACME`) to a canonical node via
  **non-destructive** `SAME_AS` edges. Added a pipeline-level test pinning this default-on
  contract (default build emits `SAME_AS` + a `Canonical` node; `resolve_entities=False`
  removes them); `textgraph er audit` verified working.
- **Flagged (G2 conflict, not implemented):** the backlog asked to make **Splink** the
  default ER step, described as "no new heavy dependencies." It is not — Splink pulls in
  `splink` + `duckdb` + `pandas`, which would bloat the lean local-first default and trade
  away the moat the market review says to protect. The deterministic rules backend already
  delivers default-on resolution; **Splink stays the opt-in `[er]` backend.** Quality
  improvements to alias/synonym handling are tracked for Sprint 3.

### Added — console "Ask" chat (grounded, deterministic)
- **A chat dock in `textgraph console`.** Ask a question in plain English; it is *routed* to
  the right graph tool (reason / search / path / why / neighbors / timeline / contradictions /
  communities / stats / gql) and answered with a **templated, cited** reply that also
  **highlights the answer's nodes and path on the graph beside it**. Every reasoning step is
  shown as a collapsible thought-chain artifact, and each fact carries its `[doc:span]`
  citation — no LLM, fully deterministic and offline (G1/G2/G3).
- **Multi-turn, stateless server:** follow-ups ("why?", "who controls it?") resolve their
  missing entity against the previous answer's focus, passed by the client. New pure
  `textgraph/console/chat.py` (`answer()` + intent `classify()`), a `POST /api/chat` route,
  and `do_POST` on the console server. The offline `graph.html` (no server) hides the dock
  gracefully. +8 tests.
- **Attach files to the graph** (opt-in `textgraph console --allow-ingest`): drop documents
  into the chat and they are ingested into the **live** graph — written into the corpus dir
  (basename-only, extension-allowlisted, size-capped) and **incrementally** rebuilt
  (`build(root, cache_dir=…)`, byte-identical to a clean rebuild), then the engine is
  hot-swapped and the canvas + stats refresh. New `textgraph/console/ingest.py` with a
  stdlib `multipart/form-data` parser (`cgi` was removed in 3.13), `POST /api/ingest`, and
  `/api/config` gating. Read-only stays the default; the attach control only appears when
  ingestion is enabled. +6 tests.

### Fixed — Graph-of-Thoughts access-control + cost (prerequisite for the chat)
- `GraphOfThoughts` now accepts an **injected engine** instead of always building its own, so
  it reuses the caller's already-built (and possibly policy-protected) `QueryEngine` — this
  avoids rebuilding the BM25/PPR indexes on every call **and** closes an access-control gap:
  `reason(..., context=…)` now threads a `SecurityContext` through every tool call, and
  `QueryEngine.resolve()` became **policy-aware**, so a restricted entity can no longer leak
  into a thought (e.g. via the Plan's focus list). The non-policy-aware `gql` corroboration
  is skipped under a context. +1 red-team test.

## [2.0.0] - 2026-08-06

**TextGraph 2.0 — the enterprise-extension release.** The deterministic L0–L9 core shipped
in v1.0.0; 2.0 adds four optional, flagged extension layers on top, each of which preserves
the byte-identical `graph.json` guarantee (G1) and the local-first, zero-LLM-by-default
posture (G2) — with no policy / no query they change nothing about the default install:

- **Phase 7 — GQL / ISO-GQL standards query surface** (`textgraph/gql/`, `textgraph gql`)
- **Phase 8 — vision-native late-interaction (MaxSim) retrieval** (`[vision]`, `textgraph vision`)
- **Phase 9 — enterprise fine-grained access control** (`[security]`, `textgraph secure`)
- **Phase 10 — Graph-of-Thoughts agent reasoning** (`textgraph/got/`, `textgraph reason`)

The full L0–L10 stack is now complete. Per-phase detail follows.

### Added — Phase 10: Graph-of-Thoughts agent reasoning (`textgraph/got/`)
- **A KG-grounded reasoner (ESCARGOT-style).** `GraphOfThoughts.reason(query)` builds a
  graph of thought vertices with roles (Plan / SubProblem / Hypothesis / VerificationStep /
  DistilledSummary, §4.1) using the four GoT operators — **Generation** (`neighbors`),
  **Aggregation** (`path`), **Refinement** (`why` + a `gql` triple check), **Distillation**
  (prune + summarise). Every substantive thought is **bound to real graph evidence**: its
  `[doc:start-end]` citations come from the tool that produced it, and a thought that
  gathered none is dropped — so the finished chain is verifiable end to end (G3).
- **Adaptive cost (DGoT/AGoT).** Task complexity — how many entities the query itself names
  — is measured at runtime. A simple query runs a cheap linear chain; only when complexity
  crosses a threshold does the loop spawn the parallel Aggregation/Refinement branches. A
  `static` mode expands the full topology regardless, as a baseline. The tool-call budget
  is hard-bounded (G7).
- **Deterministic and read-only.** Every tool it calls is deterministic and sorted, thought
  ids are sequential, and there is no wall-clock or randomness — reasoning is reproducible
  (G1) and never touches `graph.json`.
- **CLI:** `textgraph reason <corpus|.duckdb> "<question>" [--mode adaptive|static]` prints
  the whole cited reasoning chain, its tool-call cost, and the grounded answer.
- **DoD — cited steps + a number:** `benchmarks/reasoning.py` shows the adaptive reasoner is
  **70% cheaper** than the static-topology baseline (24 vs 80 tool calls over the fixture)
  while **every reasoning step cites real graph spans** — see `BENCHMARKS.md`.
- +11 tests (thought model, the four operators end to end, complexity gating, adaptive <
  static, grounding invariant, determinism, CLI); coverage stays ≥ 88%.

### Added — Phase 9: enterprise fine-grained access control (`textgraph/security/`)
- **ReBAC + ABAC, enforced inside traversal.** A new `[security]`-flagged layer brings
  Relationship-Based Access Control (Zanzibar/OpenFGA-style relation tuples — `owner`,
  `viewer`, `member`, `parent`, usersets, with transitive group/folder policy paths) and
  Attribute-Based Access Control (Cedar-style `MinClearance` / `IpAllowlist` / `TimeWindow`
  conditions) to the graph engine (gap-analysis §3.1).
- **Security-aware Personalized PageRank (not a post-filter).** Attach a `SecurityPolicy`
  to a `QueryEngine` and pass a `SecurityContext` per tool call: retrieval runs on a graph
  **masked to the principal's authorized nodes**, so an unauthorized node's transition
  probability is `0` and can never influence centrality, seed a walk, or surface as a hit
  (§3.2). `path` prunes restricted nodes *and edges* mid-Dijkstra; `neighbors`, `why`,
  `timeline`, `contradictions`, `communities`, and `vision_search` are all context-aware,
  and an edge is hidden unless its own source document is authorized (no leaking a
  restricted relation between two otherwise-visible entities).
- **Deterministic default, service behind the extra** (the project's upgrade-or-fall-back
  rule): the built-in `RebacStore` is pure-Python and needs no service; a real OpenFGA /
  Zanzibar deployment is opt-in behind **`[security]`** via `resolve_policy_engine`,
  import-guarded with a clean fallback to `rebac`.
- **`graph.json` is untouched.** Access control is purely query-time — with no policy (or
  no context) every tool behaves byte-identically to the un-secured engine, so the default
  install and the deterministic artifact are unaffected (G1/G2).
- **CLI:** `textgraph secure <corpus|.duckdb> "<query>" --policy policy.json --principal
  alice [--group G --clearance N --ip … --as-of DATE]` runs a search under a policy.
- **DoD — red-team + a number:** `tests/integration/test_security_redteam.py` proves
  **zero context-bleed** through PPR / paths / neighbors / summaries / vision (and that the
  leak is real without a policy); `benchmarks/security.py` measures the enforcement
  overhead (~+14% p50, full-access) and confirms transparency — see `BENCHMARKS.md`.
- +33 tests (ReBAC reachability incl. nesting/inheritance/usersets/cycles, ABAC rules,
  policy assembly, `[security]` fallback, the red-team suite, CLI); coverage stays ≥ 88%.

#### Phase 9 review — two security fixes
- **`stats()` no longer leaks unauthorized entity names.** It was the one agent tool left
  un-scoped, so a restricted (e.g. high-PageRank) entity's name and community label could
  surface through `top_entities` regardless of the caller's policy. `stats` now takes a
  `context` and computes its counts and `top_entities` over authorized content only
  (red-team assertion added; the unsecured control still surfaces them).
- **ABAC `MinClearance` now fails closed on an unmapped classification.** A document
  carrying a classification label absent from the `levels` map previously defaulted to
  level 0 (public) — silent privilege escalation on a misconfigured policy. A classified
  (non-empty, unmapped) label is now denied; an unclassified (empty) resource stays public.

### Added — Phase 8: vision-native late-interaction retrieval (`textgraph/l8_retrieval/vision/`)
- **ColPali-style page retrieval, MaxSim and all.** A query and a document-as-**page** are
  each a **multi-vector**, scored by the late-interaction **MaxSim** operator
  `sum_i max_j (q_i · p_j)` (gap-analysis §2.1). The engine gains `vision_search()` /
  `textgraph gql`-sibling `textgraph vision "<query>"`, ranking pages by MaxSim.
- **Deterministic default, model behind the extra** (the project's upgrade-or-fall-back
  rule): the `hash` embedder maps tokens to fixed unit vectors (SHAKE-256, pure stdlib),
  so the whole late-interaction pipeline runs and is unit-tested reproducibly with **zero
  GPU** (G1/G2). `vision_backend='colpali'` requests a real ColPali/ColQwen model over
  rendered page images behind the **`[vision]`** extra — import-guarded, falling back to
  `hash` if absent.
- **`graph.json` is untouched.** Embeddings are computed at query time only; pages are
  documents (already seeding PageRank via their entity mentions), so the default install
  and the byte-identical artifact are unaffected — verified.
- **DoD — a benchmarked number:** `BENCHMARKS.md` now reports the vision channel next to
  text: on the fixture, MaxSim/hash page retrieval scores **recall@5 0.80** (vs 0.70 for
  text) at higher cost (196 vs 131 tokens/query, ~11 ms) — real quality *and* cost. The
  `[vision]` model is where image-native gains land (not CI-benchmarkable without a GPU).
- +7 tests (MaxSim math, deterministic embedder, retriever, engine `vision_search`,
  `[vision]` fallback); 244 total, coverage 89%.

### Added — Phase 7: GQL / ISO-GQL standards layer (`textgraph/gql/`)
- **A standard graph-query surface over the property graph.** A pure-Python,
  deterministic subset of **GQL (ISO/IEC 39075) / Cypher** — tokenizer + recursive-descent
  parser + executor — so enterprise agents can query TextGraph the way they query any GQL
  backend (Neo4j, Memgraph, Kùzu), not through a bespoke API. Runs against the *same*
  `(nodes, edges)` the L8 tools use; **read-only, so G1/G2/G3 are untouched** and
  provenance stays reachable via edge properties.
- **Supported:** property-graph pattern matching `(a:Label {k:v})-[r:TYPE]->(b)` in all
  directions; **quantified (variable-length) relationships** `-[:T*min..max]->` (loop-free,
  depth-capped, G7); `WHERE` with `= <> < <= > >= CONTAINS STARTS WITH ENDS WITH IN`,
  `AND`/`OR`/`NOT`; `RETURN` with properties, `type()`/`labels()`/`id()`, `count(*)`
  aggregation and `AS`; `DISTINCT`, `ORDER BY … ASC|DESC`, `SKIP`, `LIMIT`. Result rows are
  stably ordered (deterministic).
- **CLI:** `textgraph gql <corpus|graph.duckdb> "MATCH (a)-[:CONTROLS]->(b) RETURN a.name, b.name"`.
- **DoD met:** the pattern-based tools **round-trip** — `neighbors`, `path` (quantified
  pattern), and `contradictions` expressed as GQL return results matching the typed tools
  on a fixture.

### Fixed — Phase 7 review (GQL hardening)
- **Malformed integer clauses no longer crash.** `LIMIT 2.5`, `SKIP 1.5`, `*1.5..3` raised
  a raw `ValueError` (an uncaught traceback at the CLI); they now raise a positioned
  `GQLError`.
- **Reused variables are a join constraint.** `(a)-[*1..2]->(a)` used to rebind `a` to
  every reachable node (returning "any path"); it now correctly means a **cycle** — a
  repeated variable must bind to the same element (proper Cypher/GQL semantics).
- **Undeclared variables are rejected.** `MATCH (:Entity) RETURN n.name` (or `… IN foo`)
  silently returned rows of NULL; it now errors with `unknown variable(s) not bound by the
  pattern`, catching typos instead of hiding them.
- **Negative number literals** (`WHERE n.x > -1`) now parse.
- +4 regression tests; 237 total, coverage 89.5%.

### Changed — v1.1: retrieval quality + wider coverage gate
- **Hybrid search reranking (`l8_retrieval/rerank.py`).** The raw RRF fusion broke ties
  by node id, which (since `chunk:` < `entity:`) buried every answer-entity beneath every
  passage — so "who controls Gamma Holdings" didn't even return Acme Corp in the top 5. A
  second-stage reranker now scores each kind by fusion score + lexical overlap and
  **interleaves** entities with passages (the answer node and its evidence, alternating).
  On the fixture benchmark: **recall@5 0.60 → 0.70, MRR 0.29 → 0.80**, tokens/query 163 →
  131 — deterministic. A cross-encoder reranker is the opt-in `[rerank]` extra
  (import-guarded, clean fallback). `BENCHMARKS.md` regenerated.
- **Coverage gate widened from `core/` to the whole package** (`fail_under` 80 → 88;
  actual ~90%), omitting only the import-guarded backends and socket-bound servers that
  run in dedicated jobs. Closes the last v1.1 debt item.

### Added — interactive graph console (toward v1.1)
- **`textgraph console` is now a real graph viewer.** A hand-rolled, dependency-free
  HTML5 **canvas** renderer draws the graph the way an investigator expects: nodes
  coloured by L7 community and sized by PageRank, pan/zoom/hover, a **Communities
  sidebar** with per-cluster toggles + "Select All" (counts and colour dots), a
  **confidence-tag filter** (so `GENERATED` output is visibly quarantined), hybrid
  **search** that highlights matching nodes and lists cited passages, **click-to-inspect**
  (a node's cited claims with `[t_valid, t_invalid)` windows, superseded ones flagged),
  a **path** mode that traces the maximum-likelihood chain between two clicked nodes,
  and a **temporal slider** — scrub a date and superseded claims fade out (the edge's
  `[t_valid, t_invalid)` window drives it; the label turns red the moment a correction
  supersedes an assertion). Nothing else on the market visualizes bi-temporal
  invalidation — and here it falls straight out of the L6 model.
- **Deterministic server-side layout (`l7_analytics/layout.py`).** Fruchterman-Reingold
  with community-aware gravity, **hash-seeded (no RNG) and fixed-iteration**, coordinates
  rounded and baked onto entity nodes as `x`/`y`. `graph.json` stays byte-identical (G1);
  the browser only *draws* the precomputed layout, never runs physics. Bounded for large
  graphs (top-N by PageRank + induced edges, with a visible "showing N of M" note, G7).
- New `/api/graph` endpoint + `QueryEngine.graph_view()`; zero external requests (G2).
- **The offline `graph.html` artifact is now the same interactive viewer.** The canvas
  renderer, CSS, and skeleton live in one shared module (`console/renderer.py`) driven by
  a small `TG` adapter, so the live console and the emailed file **never drift**: the
  console feeds it over `/api`, and `graph.html` embeds the graph + per-node cited claims
  and runs **client-side** path (Dijkstra over `-log(confidence)`) and search — fully
  interactive with no server. Retires the old concentric-ring SVG stub.
  +3 tests (temporal windows, offline viewer, layout); 214 total.

## [1.0.0] - 2026-08-04

First stable release. TextGraph turns any text corpus into a deterministic, fully
provenanced knowledge graph and makes it queryable by agents and humans alike — the
complete L0-L9 layer stack (Phases 0-6):

- **L0-L1** deterministic ingest + structural spine; **L2-L3** encoder IE (entities +
  typed relations); **L5** non-destructive entity resolution.
- **L6** citable, **bi-temporal** claims — corrections *invalidate* rather than delete.
- **L7** pure-Python analytics (PageRank, communities, contradictions).
- **L8** HippoRAG-style dual-node retrieval: eight typed, bounded, **cited** tools over
  a hybrid BM25 + Personalized-PageRank engine, exposed identically via the CLI, an MCP
  server, and a local web **console**.
- **L4** opt-in LLM synthesis, `GENERATED`-tagged and quarantined; **off by default**.
- **L9** byte-stable `graph.json` + report/HTML/manifest; DuckDB persistence and
  incremental `watch` rebuilds.

Every non-generated edge carries a re-verifiable byte-range citation; `graph.json` is
byte-identical across rebuilds (CI-gated); the default path is local-first and
zero-LLM. 207 tests, strict types, determinism + provenance gates green.

### Added — Phase 6: local console + packaging
- **`textgraph console <path>`** — a dependency-free, read-only web UI over the L8
  `QueryEngine` (`textgraph/console/`): all eight typed tools (search / neighbors / path
  / why / timeline / contradictions / communities / stats) in the browser, each result
  cited, validity windows shown for temporal claims. Built on stdlib `http.server`; the
  page is self-contained (inline CSS/JS, no CDN, G2) and theme-aware. Serves a corpus or
  a persisted `.duckdb` snapshot. Routing is a pure `route()` function, unit-tested
  without a socket (+6 tests).
- **Packaging verified for ship:** wheel builds cleanly and bundles the new packages
  (`console`, `l4_llm_optional`, `store/duckdb_store`, `watch`) with the `textgraph`
  console-script entry point.

### Added — Phase 6: optional LLM pass (L4)
- **Model-authored community summaries, quarantined by tag.** Opt-in L4
  (`l4_llm_optional/`) asks an LLM to summarize the largest L7 communities using *only*
  the facts passed to it, and emits a `Summary` node + `SUMMARIZES` edges tagged
  **`GENERATED`** — so model output can never be mistaken for an extracted, cited fact
  (G4). Enabled with `textgraph build --llm`; **off by default**, so the determinism
  gate never sees an LLM and `graph.json` stays byte-identical (G1, G2).
- **Dependency-free, OpenAI-compatible client** (`client.py`, stdlib `urllib`): works
  against OpenAI, vLLM, Ollama, or any `/chat/completions` endpoint via `base_url`. The
  **API key is read from the environment only** (`API_KEY` / `TEXTGRAPH_LLM_API_KEY` /
  `OPENAI_API_KEY`) — never stored on `Config`, hashed into `config_hash`, or written to
  an artifact. An unconfigured `--llm` build skips L4 rather than failing.
- **Hard-budgeted + cached** (`cache.py`, G7): at most `llm_max_calls` communities are
  summarized (biggest first), and responses are cached by a content hash of
  `(model, system, user, params)` so a warm rebuild is reproducible and free.
- `manifest.json` gains an `L4` stage + `summaries` coverage and reflects `llm_enabled`.
  +8 tests (mock client, no network); 200 total.

### Added — Phase 5: temporal + incremental
- **Bi-temporal claims (L6) — invalidation, not deletion.** When two claims about the
  same `(subject, predicate, object)` disagree in polarity, the later-dated one
  *supersedes* the earlier: the earlier claim's `t_invalid` is closed to the later
  claim's `t_valid`, and a cited `SUPERSEDES` edge records the correction. The
  superseded claim stays in the graph, so an agent can still ask *what was believed
  true, and when it changed* (`l6_graph_model/temporal.py`). Ordering uses only
  **valid-time dates stated in the corpus** (compared lexically — ISO dates sort
  chronologically); no wall-clock (G1). An undated conflict can't be ordered, so it's
  left open and still surfaces via L7 `CONTRADICTS`. `ClaimView` gains `t_invalid` +
  `status`; `timeline` / `why` / `contradictions` and `textgraph explain` show the
  `[t_valid, t_invalid)` window. New `invalidate_claims` config flag.
- **Persistent `DuckDBGraphStore`** (`store/duckdb_store.py`, behind `[graph]`/`[er]`).
  Import-guarded; serializes the assembled graph to a DuckDB file with an **exact**
  Node/Edge round-trip, so a graph **loads from disk without a rebuild**. `textgraph
  build --store PATH.duckdb` persists; any query verb given a `.duckdb` path loads it.
- **Incremental rebuild (G5).** `build(..., cache_dir=…)` caches per-document IE keyed
  by `(doc_id, config_hash)` (`core/incremental.py`), so editing one file re-extracts
  only that file — and the incremental build is **byte-identical** to a full build.
- **`textgraph watch <dir>`** (`watch.py`): content-addressed change detection (blake3,
  not mtime) triggers an incremental rebuild + artifact re-write; refuses an output/cache
  dir nested inside the watched corpus (would re-ingest its own artifacts).
- **CLI parity:** all eight L8 tools now have verbs — `neighbors`, `timeline`,
  `contradictions`, `communities`, `stats` join `query` / `path` / `explain`, over the
  same `QueryEngine` the MCP server uses.
- +17 tests (temporal, incremental, watch, DuckDB round-trip, CLI verbs); 193 total,
  determinism + provenance hold across the new `corpora/temporal` fixture.

### Added — Phase 4: Retrieval (L6 + L7 + L8 + MCP)
- **The graph is queryable.** Same `QueryEngine` drives the new CLI verbs
  (`textgraph query|path|explain`) and the MCP tool surface — an agent answers through
  typed tools alone, never raw Cypher (G6).
- **L6 claim reification (`l6_graph_model/claims.py`)** — every entity→entity relation
  edge becomes a first-class, citable `Claim` node (subject/predicate/object/polarity/
  modality/confidence) with a temporal window; the direct edge is kept. `t_valid` is
  grounded to the nearest `Date` in the same sentence (byte proximity); `t_invalid`
  stays null (full bi-temporal invalidation is Phase 5). No wall-clock in the graph.
- **L7 analytics (`l7_analytics/`)** — deterministic weighted **PageRank** + **Brandes
  betweenness** (`algorithms.py`), **label-propagation communities** with c-TF-IDF
  labels (`communities.py`), and diagnostics (`analyze.py`): **god nodes** (central on
  both measures), **bridges**, orphans, **contradictions**. `enrich.py` writes
  centrality/community onto entity nodes and emits `CONTRADICTS` edges between
  conflicting `Claim` nodes.
- **L8 retrieval (`l8_retrieval/`)** — HippoRAG-style **dual-node graph** (`Chunk`
  passage nodes + `chunk -[MENTIONS]-> entity` links, `emit_chunks.py`) with eight
  typed, bounded, cited tools (`engine.py`): `search` (pure-Python **BM25** in
  `bm25.py` fused with **Personalized PageRank** by **RRF**, local/global routing),
  `neighbors`, `path` (**maximum-likelihood**, Yen's k-shortest under `-log(confidence)`),
  `why`, `timeline`, `contradictions`, `communities`, `stats`. Every result is a
  token-budgeted context pack (`model.py`) with a `[doc:start-end]` citation on each row.
- **MCP surface (`textgraph/mcp/`)** — `tools.py` (specs + dispatcher, no `mcp`
  dependency, CI-tested) and `server.py` (stdio adapter behind the `[mcp]` extra).
- **First retrieval benchmark** (`benchmarks/retrieval.py`, `BENCHMARKS.md`) — recall@k
  / MRR reported *with* tokens-per-query and p50/p95 latency ("no number without its
  cost"); external LoCoMo/LongMemEval-S sets run only when data is present locally.
- **graph.json** now carries `Claim` nodes, `Chunk` nodes (with text), entity
  centrality/community properties, and `CONTRADICTS` edges — still byte-identical across
  rebuilds. `manifest.json` gains L6/L7/L8 stages + claim/community/contradiction/chunk
  coverage; `GRAPH_REPORT.md` gains Communities and Contradictions sections.
- **Tests:** L6/L7/L8/MCP unit suites + a tool-only **agent-session** integration test
  that verifies every answer's byte citations; 170 total. Determinism and 100%
  edge-provenance re-verification hold with L6–L8 in the loop, including a new
  opposite-polarity contradiction fixture.

### Fixed — Phase 4 review
- **`search` fabricated hits for no-match queries.** With an empty seed the Personalized
  PageRank teleport is uniform, so it re-emitted degree centrality — surfacing arbitrary
  entities for a query that matched nothing lexically or by name. Entity ranking is now
  gated on a real seed signal; a true no-match returns zero hits.
- **Dangling `CONTRADICTS` edges when reification is off.** `CONTRADICTS` links `Claim`
  nodes, so with `reify_claims=False` (L6 disabled) it pointed at nodes that don't
  exist. Emission now skips any pair whose claims aren't present in the graph.
- **`neighbors` buried relations under provenance edges.** `MENTIONS` / `HAS_CHUNK`
  (confidence 0.9) outranked real `TRANSFERRED` / `CONTROLS` relations (0.78); these
  membership edges are now hidden from `neighbors`, so semantic connections surface.
- **k-shortest paths were incomplete.** `path`'s Yen search discarded spur paths that
  looped through root nodes instead of routing around them; the spur Dijkstra now blocks
  root nodes, so genuine alternate paths are found.
- **Leiden was promised but not wired.** `analytics_backend="leiden"` now runs a real
  import-guarded Leiden pass (`igraph` + `leidenalg` behind `[graph]`) that raises
  `UnsupportedFormat` and falls back to the deterministic built-in when absent — matching
  the architecture's upgrade-or-fall-back pattern (the config field was previously dead).

### Added — Phase 3: Entity Resolution (L5)
- **Alias entities collapse to a canonical identity.** `Acme Corp` / `Acme
  Corporation` / `ACME` resolve to one canonical **"Acme Corporation"** node;
  `Beta Ltd` / `Beta Limited` → "Beta Limited"; unrelated `Alpha Bank` stays separate.
- **Blocking** (`blocking.py`): deterministic keys (suffix-stripped name, acronym,
  first-token), type-gated. Blocking recall gated ≥ 0.99 in CI.
- **Scoring** (`scoring.py`): Jaro-Winkler + token-set + acronym match + the
  graph-native **relational** shared-neighbour signal. Splink (Fellegi-Sunter on
  DuckDB) scaffolded behind the `[er]` extra.
- **Clustering** (`clustering.py`): complete-linkage agglomeration with a cohesion
  threshold — prevents the classic over-merge catastrophe (one bad edge merging two
  galaxies). Verified by a chain-merge unit test.
- **Non-destructive** `SAME_AS` lattice (`emit_er.py`): original entity nodes kept; a
  new `("Entity","Canonical",<etype>)` node links members via INFERRED, span-cited
  `SAME_AS` edges — fully reversible and auditable (§8.3).
- **`textgraph er audit`** command renders proposed merges with match scores for
  human review; **B-cubed metrics** (`metrics.py`) with a pinned F1 floor gated in
  CI; the god-node diagnostic flags an injected over-merge.
- **IE now runs per prose block** (not whole-doc text), so an entity can't span a
  heading→paragraph boundary; **acronym-of-known-org** detection links `ACME` to
  `Acme Corp`. Manifest reports canonical/SAME_AS/blocking counts; report gains a
  "Resolved entities (SAME_AS)" section; ablation shows the ER contribution.
- 133 tests, ~97% core coverage; determinism holds with L5 in the loop.

### Fixed — Phase 3 review
- **False Person from heading title-case** ("Corporate Aliases") — the person-bigram
  heuristic is disabled for headings, and `_PERSON_CUE` no longer uses global
  `IGNORECASE` (which had let "director on paper only" capture a lowercase "person").
- **ER over-merge: conflicting suffix families.** "Acme Bank" and "Acme Corp" (same
  base, different legal form) were merged by the suffix-stripped exact match. Added a
  `suffix_family` classifier; same-base names with conflicting families now score
  below the match threshold. Corp/Corporation, Ltd/Limited, Inc/Incorporated remain
  the same family, so true aliases still merge.
- **ER over-merge: shared suffix inflating similarity.** "Acme Corp" vs "Apex Corp"
  scored 0.867 (> 0.86) because the shared "Corp" lifted Jaro-Winkler over threshold.
  Name similarity is now computed on the suffix-stripped base name ("acme" vs "apex"
  → 0.70), so distinct companies no longer merge.

### Added — Phase 2: Encoder IE (L2 + L3)
- **The build now produces a real knowledge graph, not just a structural spine.**
- **L2 linguistic substrate** (`textgraph/l2_linguistic/`): deterministic sentence
  segmentation, coreference-lite (pronoun/definite-NP → nearest compatible entity),
  and NegEx-style negation/modality detection.
- **L3 encoder IE** (`textgraph/l3_encoder_ie/`): entity + relation extraction with a
  backend interface. Default `rules` backend is deterministic, zero-model, CPU-only —
  detects Organization/Person/Money/Account/Date/Email entities and TRANSFERRED
  (with amount) / CONTROLS / BENEFICIAL_OWNER_OF / DIRECTOR_OF / ASSOCIATED_WITH
  relations; predicate canonicalization keeps the surface form as evidence. GLiNER
  backend scaffolded behind the `[ie]` extra (import-guarded, pinned model id).
- **Full four-tier confidence taxonomy (G4)** now exercised end-to-end: `STRUCTURAL`
  (L1), `EXTRACTED` (L3 entities/relations), `INFERRED` (coref-resolved relations),
  with `GENERATED` reserved for the Phase-6 LLM pass. Negation/modality preserved as
  edge attributes (never dropped).
- **Manifest** reports per-layer L0–L3 counts and **coref coverage**
  (`resolved/total` pronouns); `schema.yaml` records observed entity/relation types.
- **`GRAPH_REPORT.md`** gains Entities and Key-relationships sections and
  relationship-shaped suggested questions ("Follow the money…").
- **Config**: `extract_ie` (default true) and `ie_backend`; `Config(extract_ie=False)`
  builds the structural spine only.
- **Ablation harness** (`benchmarks/run.py`): L1-only vs. +encoder IE, showing the
  node/edge/entity/relation delta and coref coverage — deterministic and diffable.
- **Tests**: L2/L3 units + IE-pipeline integration (entities/relations, coref,
  negation, hedging, all-tags, provenance re-verification, byte-identical rebuild).
  Determinism gate stays green with IE in the loop. 112 tests, ~97% core coverage.

### Fixed — Phase 2 review pass
- **Coref coverage was double-counted.** `_Coref.resolve()` (used for relation
  slot-filling, called repeatedly per slot) incremented the same counters that
  `count_coverage()` uses, inflating `resolved/total` in `manifest.json`. `resolve()`
  is now a pure lookup; coverage is computed once over all pronouns.
- **Sentence segmenter treated org suffixes as abbreviations.** `Ltd.`/`Inc.`/
  `Corp.`/`Co.` were in the abbreviation list, so "...Beta Ltd. Acme Corp acted."
  never split — a run-on sentence that could misattribute relation subjects. Those
  suffixes (which routinely end sentences, unlike titles) were removed.
- **`MENTIONS` edges aggregated.** Instead of one edge per mention, each entity now
  has a single `MENTIONS` edge with `evidence_count` and all occurrence spans —
  surfacing repetition as a precision signal (§6.4) and shrinking the edge set.
- **Cross-document `mention_count`.** An entity appearing in several documents now
  reports its corpus-wide mention total, not just the first document's.

### Added — Phase 1: Structural Spine (L0 + L1)
- **Mission focus:** positioned for financial-crime and technical-crime
  investigation — surfacing who/what is connected and *why*, with audit-grade
  provenance. README and docs reframed accordingly.
- **L0 ingestion** with a format registry and hierarchical, heading-aware chunking:
  - built-in (stdlib/pure-Python): markdown (markdown-it-py AST), plain text,
    HTML/XHTML, DOCX, ODT, RTF, EPUB, JSON/YAML/TOML, logs (template mining),
    transcripts (speaker turns).
  - PDF behind the `[ingest]` extra (pypdf); missing extras are skipped with a
    warning, never a crash (G2).
  - byte-preserving formats cite original file bytes; derived-text formats
    (docx/pdf/odt/epub/rtf/html) make the extracted text the canonical document and
    every span still re-verifies against it (G3).
- **L1 deterministic structure parse** (zero models): Document/Section hierarchy
  (`CONTAINS`), links (`LINKS_TO`), definitions (`DEFINES`/Term), citations
  (`CITES`), cross-references (`REFERENCES`), structured fields (`HAS_FIELD`),
  transcript threads (`PARTICIPANT`/`SENT_BY`/`REPLIES_TO`), log templates
  (`EMITS`), and **Rationale / Requirement** nodes from markers (WHY/DECISION/
  TODO/ACTION/ADR + RFC-2119 MUST/SHALL/…). Every edge is `STRUCTURAL`,
  confidence 1.0, with a re-verifiable source span.
- **In-memory `GraphStore`** backend (deterministic ordering).
- **L9 artifacts**: byte-stable `graph.json` (schema-conformant), `GRAPH_REPORT.md`
  with 10 grounded questions, self-contained `graph.html` (no CDN, precomputed
  layout, click-to-source-span), `schema.yaml`, `manifest.json`.
- **CLI**: `textgraph build <path> -o DIR` writes the artifact set; `--json-only`
  writes just graph.json.
- **Tests**: L0/L1/rich-format/report/artifacts suites; determinism gate extended
  to three corpus shapes (docs, ADR, chat); edge-level provenance re-verification
  across every fixture corpus; graph.json/manifest.json validated against JSON
  Schema. 91 tests, ~97% core coverage.

### Fixed
- **Non-UTF-8 ingestion crash.** `normalize()` decoded with strict UTF-8, so any
  undecodable byte (OCR output, mixed-encoding logs, binary-ish content — all in
  the L0 format matrix) raised `UnicodeDecodeError` and crashed `textgraph build`.
  Now decodes with `surrogateescape`: each undecodable byte becomes one lone
  surrogate that re-encodes to the exact original byte, so offset fidelity (G3)
  and determinism (G1) are preserved and the pipeline degrades gracefully (§5.4).
  Added regression tests and a `mixed-encoding.log` fixture (pinned binary) that
  flows through the determinism and provenance-integrity gates.

### Notes
- Read all three source documents in full (research `.md`, blueprint PDF, gap
  analysis DOCX) and reconciled Phase 0 against them. Recorded the §4.2-vs-§6.4
  L1 confidence-tag discrepancy in `ARCHITECTURE.md` (resolved to `STRUCTURAL`).

### Added — Phase 0: Repository & CI/CD foundation
- Repository scaffold for the full L0–L9 layer stack (`textgraph/l0_ingest` …
  `l9_artifacts`, `store/`, `mcp/`).
- Core primitives, fully unit-tested:
  - blake3 content addressing (`doc_id`, span re-verification).
  - Run-length-encoded offset maps (canonical char span → raw byte span).
  - `CanonicalDoc` + UTF-8/CRLF/BOM-safe normalization.
  - Canonical JSON serialization (byte-stable output, G1).
  - Pinned `Config` + config hashing.
- `GraphStore` interface with the four-tier confidence taxonomy and byte-span
  provenance types.
- Trivial deterministic pipeline + `textgraph build` / `textgraph version` CLI.
- CI: lint-and-typecheck, test (Python 3.11/3.12 matrix, coverage gate on `core/`),
  **determinism** (byte-identical `graph.json`), pre-commit, benchmark (nightly),
  and release (re-runs determinism against the built artifact).
- JSON Schemas for `graph.json` and `manifest.json`; `schema.yaml` template.
- Docs: `ARCHITECTURE.md`, `docs/SKILL.md`, `docs/how-it-works.md`, `SECURITY.md`,
  `PLAN.md`.
