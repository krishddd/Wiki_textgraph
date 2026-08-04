# Changelog

All notable changes to TextGraph are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to Semantic Versioning.

## [Unreleased]

### Added — interactive graph console (toward v1.1)
- **`textgraph console` is now a real graph viewer.** A hand-rolled, dependency-free
  HTML5 **canvas** renderer draws the graph the way an investigator expects: nodes
  coloured by L7 community and sized by PageRank, pan/zoom/hover, a **Communities
  sidebar** with per-cluster toggles + "Select All" (counts and colour dots), a
  **confidence-tag filter** (so `GENERATED` output is visibly quarantined), hybrid
  **search** that highlights matching nodes and lists cited passages, **click-to-inspect**
  (a node's cited claims with `[t_valid, t_invalid)` windows, superseded ones flagged),
  and a **path** mode that traces the maximum-likelihood chain between two clicked nodes.
- **Deterministic server-side layout (`l7_analytics/layout.py`).** Fruchterman-Reingold
  with community-aware gravity, **hash-seeded (no RNG) and fixed-iteration**, coordinates
  rounded and baked onto entity nodes as `x`/`y`. `graph.json` stays byte-identical (G1);
  the browser only *draws* the precomputed layout, never runs physics. Bounded for large
  graphs (top-N by PageRank + induced edges, with a visible "showing N of M" note, G7).
- New `/api/graph` endpoint + `QueryEngine.graph_view()`; zero external requests (G2).
  +5 tests (layout determinism + graph endpoint); 212 total.

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
