# Changelog

All notable changes to TextGraph are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to Semantic Versioning.

## [Unreleased]

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
