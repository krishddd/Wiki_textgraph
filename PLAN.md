# TextGraph — PLAN.md

> Written before any pipeline code, per Section 10 of the master build prompt. Phase 0 is the repo + CI/CD foundation.

## 1. The core translation problem (in my own words)

Graphify gets its guarantees — determinism, locality, provenance, cost linearity — *for free*, because source code is defined by a formal grammar. A tree-sitter parser is a pure, total function from bytes to a concrete syntax tree: the same file always yields the same tree, every node has an exact byte span, and a one-line edit only re-parses locally. Natural language hands you none of this. There is no free, deterministic, total parser for English prose; the "grammar" is statistical, ambiguous, and context-dependent, and the tools that approximate it (NER, coreference, relation extraction, LLMs) are heavier, fuzzier, and — if used naively — non-deterministic and unbounded in cost. The central engineering problem of TextGraph is therefore: **how do you recover Graphify's four guarantees for a domain that does not give them to you for free?**

The answer this architecture commits to is *stratification*. Rather than throwing the whole corpus at one probabilistic model, extraction is split into layers ordered by how much trust and non-determinism each introduces: a fully deterministic structural spine (L0/L1, zero models) is built first and is always sufficient to ship a usable graph; encoder-based information extraction (L3) runs next with pinned weights and fixed seeds so it is *reproducibly* non-trivial rather than random; an LLM pass (L4) is quarantined behind an explicit opt-in flag, hard-budgeted, cached, and tagged `GENERATED` so its output can never be mistaken for ground truth. Every layer is a pure function of the layer below it plus a pinned config hash, every edge carries a re-verifiable byte-range citation and one of four confidence tags, and contradictions are invalidated rather than deleted. In effect, the non-determinism that natural language forces on you is *isolated, pinned, tagged, and made auditable* — never allowed to leak into the parts of the system that promise determinism.

## 2. Confirmed tech-stack decisions

| Decision | Choice | Notes / deviations |
|---|---|---|
| Core language | Python 3.11+ | Matches encoder/NLP ecosystem. |
| Package manager | `uv` (primary) | Installed at a non-PATH location on the build machine (`0.9.18`); `pip`/`pipx` documented as fallbacks. **No deviation** from the spec's intent. |
| Content addressing | `blake3` | Prebuilt Windows wheels available; core dependency. |
| Storage (v0.1–v1.0) | NetworkX in-memory + DuckDB/Parquet on disk, behind a `GraphStore` interface | Nothing above L6 touches NetworkX directly. |
| Serialization | Canonical JSON (sorted keys, compact separators, UTF-8, trailing newline) | Underpins G1. |
| Static graph viewer | `sigma.js` + `graphology`, server-precomputed ForceAtlas2, single self-contained file | Phase 1+. |
| Pipeline console | Separate local web app (`textgraph console`) | Phase 6. |
| CI | GitHub Actions | Confirmed — repo is on GitHub (`krishddd/Wiki_textgraph`). |
| Heavy deps | Behind extras: `[full]`, `[ocr]`, `[vision]`, `[neo4j]`, `[mcp]`, `[security]` | Lean default install. |

**Deviation flagged:** the build machine is Windows 10 / Python 3.11.1. `uv` is installed but not on `PATH`; the build uses its absolute path. Mypy/ruff targets are unaffected. No spec goals change.

## 3. Roadmap (Phase 0–10) with effort estimates

| Phase | Title | Est. effort | Notes |
|---|---|---|---|
| **0** | Repo & CI/CD foundation | 1 unit | **In progress.** No pipeline code; scaffold + CI + core primitives. |
| 1 | Structural spine (L0+L1) | 3 units | First usable `graph.json`/`graph.html`/`REPORT.md`, zero models. |
| 2 | Encoder IE (L2+L3) | 4 units | Coref is highest-ROI; pin weights, keep determinism green. |
| 3 | Entity resolution (L5) | 3 units | Blocking → Splink scoring → non-destructive clustering. |
| **4** | Retrieval (L6+L7+L8) | 4 units | **Done.** Claims + analytics + dual-node hybrid retrieval + MCP; `BENCHMARKS.md`. |
| **5** | Temporal + incremental | 3 units | **Done.** Bi-temporal invalidation (L6), DuckDB persistent store, incremental cache + `watch`, CLI parity. |
| **6** | Optional LLM + UI polish + packaging | 3 units | **In progress.** L4 opt-in LLM (GENERATED summaries) ✅; UI console + packaging next. **v1.0 ship point.** |
| 7 | GQL / standards layer | 2 units | Extension. |
| 8 | Vision-native multimodal ingestion | 2 units | Extension. |
| 9 | Enterprise fine-grained access control | 3 units | Extension. |
| 10 | Dynamic agent reasoning (GoT) | 2 units | Extension. |

No reordering proposed. Phases 0–6 are strictly sequential and bottom-up (L0→L1→L2→L3→L5→L6→L7→L8→L9, with L4 last among core layers).

## 4. Open questions / assumptions

1. **Target OS / deployment.** Assuming cross-platform (dev on Windows 10, CI on Linux via GitHub Actions ubuntu-latest + a Windows matrix leg where cheap). CI matrix: Python 3.11 + 3.12.
2. **Corpus scale for v1.0.** Assuming up to ~10k docs / low-millions of edges — the range where NetworkX-in-memory + DuckDB-on-disk is comfortable and `sigma.js`/WebGL still renders. Larger scale is a post-v1.0 storage-engine swap (Phase 7 groundwork).
3. **CI target.** Assumed GitHub Actions (confirmed by repo host).
4. **Hosted/always-on product.** Assumed **out of scope** for v1.0 — TextGraph ships as a local CLI + MCP server + skill. A hosted service is future/optional.

*These are working assumptions; flag any you'd like changed.*

## 5. Repo scaffold

See Section 5.2 of the build prompt — generated in Phase 0 exactly as specified (`textgraph/` package with `core/`, `l0_ingest/`…`l9_artifacts/`, `store/`, `mcp/`, `cli.py`; `ui/`, `schema/`, `tests/{unit,integration,determinism,fixtures}`, `benchmarks/`, `docs/`, `.github/workflows/`, root docs).

---

## Phase 6 — Definition of Done (in progress)

- [x] **L4 optional LLM (`l4_llm_optional/`)**: opt-in (`build --llm`), off by default;
      GENERATED community summaries (`Summary` nodes + `SUMMARIZES` edges), quarantined by
      tag so they never masquerade as cited facts; dependency-free OpenAI-compatible
      client with the API key read from the environment only (never hashed/persisted);
      hard-budgeted + response-cached; determinism holds (byte-identical with LLM off).
      Verified live against a vLLM Nemotron endpoint; 8 mock-client tests in CI.
- [ ] UI / `textgraph console` (local web app over the QueryEngine)
- [ ] Packaging polish for v1.0 (wheels, entry points, docs)

## Phase 5 — Definition of Done (met)

- [x] **Bi-temporal claims (L6)**: later-dated opposite-polarity claims supersede
      earlier ones — `t_invalid` closed + cited `SUPERSEDES` edges (invalidation, not
      deletion). Ordering from in-text dates only (no wall-clock, G1); undated conflicts
      left open and surfaced via `CONTRADICTS`. `timeline`/`why`/`contradictions` +
      `explain` show the `[t_valid, t_invalid)` window. `corpora/temporal` fixture.
- [x] Persistent `DuckDBGraphStore` behind the `GraphStore` ABC (`[graph]`/duckdb extra),
      import-guarded; exact Node/Edge round-trip; `build --store` + `.duckdb` query paths
      load without a rebuild.
- [x] Incremental rebuild: per-document IE cache keyed by `(doc_id, config_hash)`;
      byte-identical to a full build; `textgraph watch <dir>` (content-addressed change
      detection, refuses nested output dir).
- [x] CLI parity: `neighbors` / `timeline` / `contradictions` / `communities` / `stats`
      verbs over the same `QueryEngine`; 193 tests; determinism holds.

## Phase 4 — Definition of Done (met)

- [x] L6 claim reification: relation edges → citable `Claim` nodes with `t_valid`
      grounded to the nearest in-sentence `Date` (`t_invalid` deferred to Phase 5);
      direct edges preserved; reified edges re-verify against raw bytes
- [x] L7 analytics (pure-Python, deterministic): weighted PageRank + Brandes
      betweenness + label-propagation communities (c-TF-IDF labels); god nodes,
      bridges, orphans, contradictions; folded into the graph as node properties +
      `CONTRADICTS` edges. Leiden behind `[graph]`
- [x] L8 dual-node retrieval graph (entity + `Chunk` nodes) + eight typed tools:
      `search` (BM25 + Personalized PageRank + RRF, local/global routing), `neighbors`,
      `path` (maximum-likelihood k-shortest), `why`, `timeline`, `contradictions`,
      `communities`, `stats` — every result bounded (token budget) and `[doc:span]`-cited
- [x] MCP surface (`textgraph.mcp` specs + dispatcher, CI-tested; stdio server behind
      `[mcp]`) + CLI `query` / `path` / `explain` over the *same* `QueryEngine`
- [x] First retrieval benchmark with cost: recall@k / MRR + tokens/query + p50/p95
      latency → `BENCHMARKS.md`; LoCoMo/LongMemEval-S guarded by local data presence
- [x] Agent-session integration test: answers via tool calls only, every citation
      re-verified against raw bytes; determinism CI still byte-identical (166 tests)

## Phase 3 — Definition of Done (met)

- [x] Blocking (deterministic keys, type-gated) + scoring (Jaro-Winkler + relational
      shared-neighbour) + non-destructive complete-linkage clustering
- [x] `SAME_AS` lattice to canonical nodes; original entities preserved (reversible)
- [x] `textgraph er audit` command; B-cubed metrics gated in CI (F1 ≥ 0.9 floor)
- [x] Blocking recall ≥ 0.99 on the ER fixture
- [x] god-node diagnostic flags an intentionally-injected over-merge
- [x] "Acme Corp" / "Acme Corporation" / "ACME" collapse; "Alpha Bank" stays separate
- [x] Splink behind `[er]`; determinism holds with L5; 133 tests, ~97% coverage

## Phase 2 — Definition of Done (met)

- [x] L2 substrate (sentences, coref-lite, negation/modality) + L3 entity/relation
      extraction; default deterministic rule backend, GLiNER behind `[ie]`
- [x] `textgraph build` produces entities (Org/Person/Money/Account/Date/Email) and
      typed relations (TRANSFERRED/CONTROLS/DIRECTOR_OF/…), tagged EXTRACTED/INFERRED
- [x] four-tier confidence taxonomy wired through the graph; negation/modality kept
- [x] Determinism CI still byte-identical with IE in the loop; models pinned/seeded
- [x] coref coverage reported in `manifest.json`; `schema.yaml` records observed types
- [x] ablation harness: L1-only vs. +encoder IE (edge/entity/relation delta)
- [x] CPU-only, model-free default path (zero GPU); 112 tests green, ~97% coverage

## Phase 1 — Definition of Done (met)

- [x] L0 ingestion across md/txt/html/docx/odt/rtf/epub/json/yaml/toml/log/chat
      (PDF behind `[ingest]`); offset fidelity + hierarchical chunking
- [x] L1 zero-model structure parse incl. Rationale/Requirement nodes; every edge
      `STRUCTURAL` with a re-verifiable span
- [x] L9 artifacts: graph.json + GRAPH_REPORT.md (10 questions) + graph.html +
      schema.yaml + manifest.json; `textgraph build`
- [x] Determinism CI byte-identical across three corpus shapes
- [x] Edge-level provenance re-verification (100%) across every fixture corpus
- [x] `GRAPH_REPORT.md` 10 grounded questions on docs / ADR / chat corpora
- [x] 91 tests green; ruff + strict mypy + ~97% core coverage

## Phase 0 — Definition of Done (tracking)

- [x] Repo scaffold (Section 5.2)
- [x] `pyproject.toml` + extras + lockfile
- [x] `CanonicalDoc` / offset-map / content-addressing primitives, unit-tested
- [x] `GraphStore` interface stubbed
- [x] Canonical-JSON serialization
- [x] Trivial deterministic pipeline + `graph.json`
- [x] CI workflows: lint-and-typecheck, test (matrix), determinism, pre-commit, benchmark, release
- [x] `.pre-commit-config.yaml`
- [x] Docs stubs: ARCHITECTURE.md, SKILL.md, docs/how-it-works.md, SECURITY.md, CHANGELOG.md, BENCHMARKS.md
- [x] `uv sync && uv run pytest` green
