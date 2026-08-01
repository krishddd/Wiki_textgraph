# How TextGraph works

A plain-language walkthrough of the pipeline. Written incrementally, one section
per phase.

## Phase 0 — the foundation (current)

Before any extraction happens, TextGraph establishes the invariants that make the
whole system auditable.

### 1. Every document gets a content-addressed identity

When a file is ingested, its raw bytes are hashed with blake3. That hash *is* the
document id (`blake3:<hex>`). Two identical files get the same id; one changed byte
gets a different id. This is what lets rebuilds be incremental (only changed
content is re-analyzed) and what anchors every citation.

### 2. Raw bytes become canonical text — reversibly

Documents arrive in many encodings and line-ending conventions. TextGraph decodes
to canonical UTF-8 and normalizes newlines, but it never loses the path back to the
original bytes. An **offset map** records, per canonical character, exactly how many
raw bytes it came from — so any span of canonical text can be mapped to the precise
raw byte range that produced it.

### 3. Claims cite byte ranges, and citations are re-verifiable

A citation isn't "see document 3." It's a byte range plus the blake3 hash of those
exact bytes. Anyone can re-hash the range and confirm the claim still rests on the
same source text. If the source changes, the hash stops matching — the system can
*tell* that a citation went stale rather than silently drifting.

### 4. Output is byte-stable

The graph is serialized as canonical JSON: sorted keys, compact separators, sorted
arrays. Build the same corpus twice and you get byte-identical output. This is
enforced in CI on every change (the determinism gate).

## Later phases

- **Phase 1** — the deterministic structural spine (headings, links, tables,
  rationale markers) — zero models, already useful for docs and wikis.
- **Phase 2+** — linguistic substrate, encoder information extraction, entity
  resolution, retrieval, temporal reasoning, and the optional LLM layer.

Each phase adds capability *without* weakening the Phase 0 invariants.
