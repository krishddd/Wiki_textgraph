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

### Provenance model

A citation stores a **canonical character span**. Verification maps it back to a
**raw byte span** through the doc's offset map and re-hashes the original bytes; a
citation is valid iff the re-hash matches the stored hash. Normalization
(CRLF→LF, BOM stripping, multi-byte UTF-8) never breaks this mapping — the offset
map records exactly how many raw bytes each canonical character consumed.

## Design goals

See [README.md](README.md#design-goals-non-negotiable) for G1–G9. When goals
conflict, the lower-numbered one wins unless a phase's Definition of Done says
otherwise.

## Storage

NetworkX in-memory for compute + DuckDB/Parquet on disk as the source of truth,
both behind the `GraphStore` interface so a GQL-native engine can be swapped in
(Phase 7) without touching L6/L7/L8 call sites.
