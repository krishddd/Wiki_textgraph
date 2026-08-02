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
