# TextGraph: Engineering Research for a Graphify-Equivalent System over Pure Textual Data

**Author brief:** Dk (Harish Krishna)
**Scope:** Build a tool that ingests textual data in *any* format and emits a queryable knowledge graph, consumable as a skill (`/textgraph`) inside Claude Code, Cursor, Codex, Gemini CLI.
**Date:** August 2026
**Status:** Research + architecture specification. Every section is written to be buildable, not aspirational.

---

## 0. The Core Translation Problem

Graphify's central engineering insight is *not* "graphs are better than vectors." It is this:

> Source code has a **free, deterministic, lossless parser** (tree-sitter). So you can build a real relationship graph with zero LLM calls, zero nondeterminism, zero data egress, and near-linear cost.

Your domain — arbitrary text — has no such parser. Natural language has no ground-truth AST. This is the single hardest problem in your project, and every architectural decision below flows from how you answer it.

**The answer is not "use an LLM instead."** The answer is a **stratified extraction stack** where each layer has a different determinism/cost/recall profile, and every edge in the final graph is stamped with which layer produced it. You recover most of Graphify's guarantees by:

1. Finding the parts of text that *do* have deterministic structure (far more than people assume — Layer 1).
2. Using **encoder-based** IE models (GLiNER-class, ~200-500M params, CPU-runnable, deterministic at temp 0, batch-parallel) as the default semantic layer instead of autoregressive LLMs — this is your "tree-sitter substitute" and it is the key design bet (Layer 3).
3. Reserving LLM calls for a narrow, optional, cacheable **rationale/abstraction pass** (Layer 4).

This gives you a defensible claim that mirrors Graphify's: *"Your text never leaves your machine, extraction is reproducible, and cost is linear in corpus size, not in LLM tokens."*

---

## 1. Design Goals (rank-ordered, these drive every tradeoff)

| # | Goal | Consequence |
|---|---|---|
| G1 | **Determinism / reproducibility.** Same corpus + same version ⇒ byte-identical `graph.json`. | Pinned model weights, sorted iteration order, fixed random seeds for Leiden, no temperature > 0, canonical JSON serialization. |
| G2 | **Local-first.** Zero network calls by default. | Encoder models bundled/cached; LLM pass is opt-in with an explicit flag. |
| G3 | **Provenance for every edge.** Never emit an assertion without a byte-range citation. | Edges carry `source_spans: [{doc_id, start, end, hash}]`. |
| G4 | **Confidence stratification.** Graphify's EXTRACTED/INFERRED is a *user-trust* feature, not a technical one. Replicate it and go further. | 4-tier provenance tag (§6.4). |
| G5 | **Incrementality.** Re-running on a corpus with one changed file must not rebuild the world. | Content-addressed chunk cache + dirty-set propagation (§11). |
| G6 | **Agent-legible output.** The consumer is an LLM agent with a token budget, not a human. | Every query returns bounded, ranked, citation-bearing context (§9). |
| G7 | **Bounded, auditable cost.** | Per-stage token/time budgets emitted in the run manifest. |

---

## 2. System Architecture

```
                       ┌─────────────────────────────────────────┐
  any textual format → │ L0  INGEST & NORMALIZE                  │ → CanonicalDoc (UTF-8 + layout tree + offsets)
                       ├─────────────────────────────────────────┤
                       │ L1  DETERMINISTIC STRUCTURE PARSE       │ → Structural spine graph (0 models)
                       ├─────────────────────────────────────────┤
                       │ L2  LINGUISTIC SUBSTRATE                │ → sentences, deps, coref, discourse
                       ├─────────────────────────────────────────┤
                       │ L3  ENCODER IE (the tree-sitter analog) │ → typed mentions + typed relations
                       ├─────────────────────────────────────────┤
                       │ L4  OPTIONAL LLM SEMANTIC/RATIONALE     │ → abstractions, WHY-nodes, schema induction
                       ├─────────────────────────────────────────┤
                       │ L5  ENTITY RESOLUTION & CANONICALIZATION│ → canonical nodes, SAME_AS lattice
                       ├─────────────────────────────────────────┤
                       │ L6  GRAPH ASSEMBLY (bi-temporal, prov.) │ → property graph in store
                       ├─────────────────────────────────────────┤
                       │ L7  ANALYTICS (Leiden, centrality, PPR) │ → communities, god nodes, bridges
                       ├─────────────────────────────────────────┤
                       │ L8  RETRIEVAL ENGINE (hybrid + PPR)     │ → ranked, cited context packs
                       ├─────────────────────────────────────────┤
                       │ L9  ARTIFACTS + SKILL/MCP SURFACE       │ → graph.json / graph.html / REPORT.md / tools
                       └─────────────────────────────────────────┘
```

Each layer is a pure function of the layer below plus a pinned config hash. That property is what makes G1 and G5 achievable.

---

## 3. Layer 0 — Ingestion & Normalization

**Goal:** Turn *any* textual container into a `CanonicalDoc`: UTF-8 text + a layout tree + a bidirectional offset map back to the original bytes.

### 3.1 Format matrix

| Class | Formats | Recommended path |
|---|---|---|
| Rich documents | PDF, DOCX, PPTX, XLSX, HTML, EPUB | **Docling** (Linux Foundation project, ex-IBM Research). Gives layout analysis, reading-order detection, table structure recognition, formula/code block extraction, and a unified `DoclingDocument` Pydantic model with bounding boxes and confidence scores. Exports lossless JSON. |
| Markup | Markdown, AsciiDoc, reStructuredText, LaTeX, Org | Native AST parsers: `markdown-it-py` (token stream), `docutils`, `pylatexenc`. **Never** regex these — you have a real grammar, use it. |
| Structured text | JSON, YAML, TOML, XML, CSV/TSV, SQL DDL, .env, protobuf/IDL | Real parsers + **tree-sitter** (yes, still useful: tree-sitter has grammars for JSON/YAML/SQL/TOML). This is where you get free Graphify-grade determinism. |
| Conversational | chat logs, email (EML/MSG), Slack exports, forum dumps, issue threads | Thread-aware parsers; reconstruct reply DAGs from `In-Reply-To`/`References` headers or `thread_ts`. |
| Temporal / media-derived | WebVTT, SRT, transcripts, meeting notes | Docling supports WebVTT natively; preserve speaker turns + timestamps as first-class. |
| Logs & semi-structured | app logs, audit trails | **Drain3** log template mining → converts a log stream into a small set of templates + parameter tables. Highly deterministic, and turns 10M lines into ~200 nodes. |
| Scanned / image-only | scanned PDF, TIFF | Docling OCR pipeline (RapidOCR/Tesseract) — mark all downstream nodes with `ocr: true` and a lowered base confidence. |

### 3.2 Non-negotiable invariants

- **Offset fidelity.** Every character in `CanonicalDoc.text` maps to a `(source_file, byte_offset)`. Without this, G3 (provenance) is impossible and your citations are lies. Implement as a run-length-encoded offset map, not per-char.
- **Content addressing.** `doc_id = blake3(raw_bytes)`, `chunk_id = blake3(normalized_text || structural_path)`. This is the foundation of incrementality.
- **Normalization is recorded, not hidden.** Unicode NFC, ligature expansion, de-hyphenation across line breaks, smart-quote folding — each is a recorded transform op so you can invert back to the original bytes.
- **Language ID per block** (`fasttext-langdetect` or `lingua-py`). Routes to the right models downstream; multilingual corpora silently destroy monolingual pipelines.

### 3.3 Layout-aware chunking (do not use fixed-size chunking)

Fixed 512-token windows destroy exactly the structure you need. Use a **hierarchical chunker**:

1. Split on layout boundaries from L0 (section > subsection > paragraph > list item > table).
2. Merge upward until a target token budget (**start at ~600 tokens** — Microsoft's GraphRAG work found smaller chunks yield materially more extracted entities than larger ones, at the cost of more coreference breakage).
3. Attach the **heading breadcrumb** as a prefix context to each chunk (`Doc > §2 Architecture > §2.3 Storage`). This alone measurably improves extraction quality.
4. Apply **overlapping windows** for extraction only (SLIDE-style sliding localized context), not for storage — extract with overlap, deduplicate triples afterward, store non-overlapping chunks.

**Chunk record:**
```json
{
  "chunk_id": "b3:...",
  "doc_id": "b3:...",
  "breadcrumb": ["Doc", "§2 Architecture", "§2.3 Storage"],
  "span": [14203, 16891],
  "token_count": 612,
  "lang": "en",
  "layout_type": "paragraph|table|list|code|quote|transcript_turn",
  "prev_chunk": "b3:...", "next_chunk": "b3:..."
}
```

---

## 4. Layer 1 — Deterministic Structure Parse (Your Real Tree-Sitter Moment)

**This layer uses zero models and produces a surprisingly rich graph.** Ship this first; it's your credibility layer, and it's fast.

### 4.1 What is deterministically extractable from text

| Signal | Edge produced | Determinism |
|---|---|---|
| Heading hierarchy | `CONTAINS(section_a, section_b)` | 100% |
| Markdown/HTML links, `[[wikilinks]]`, anchors | `LINKS_TO(doc_a, doc_b#anchor)` | 100% |
| Footnotes, citations `[12]`, BibTeX keys, DOIs, arXiv IDs | `CITES(doc, work)` | 100% |
| Cross-references ("see §4.2", "as in Table 3", "Figure 1") | `REFERENCES(chunk, block)` | ~99% (regex + resolver) |
| Table structure | `Table → Row → Cell`, header-typed columns | 100% (from Docling TSR) |
| Definition lists, glossaries, `Term: definition` | `DEFINES(doc, term)` | ~98% |
| Email/chat threading headers | `REPLIES_TO(msg_a, msg_b)`, `PARTICIPANT(person, thread)` | 100% |
| JSON/YAML/XML paths | `HAS_FIELD(obj, key)`, `$ref` resolution | 100% |
| SQL DDL | `TABLE → COLUMN`, `FOREIGN_KEY` | 100% (tree-sitter-sql) |
| Frontmatter / metadata blocks | typed properties on doc nodes | 100% |
| File-system layout, naming conventions | `IN_FOLDER`, `VERSION_OF` (`spec_v1.md` → `spec_v2.md`) | high |
| Log templates (Drain3) | `TEMPLATE → PARAM`, `EMITTED_BY` | deterministic given a fixed tree |
| Structured markers: `TODO:`, `NOTE:`, `WHY:`, `DECISION:`, `ADR-003`, `RFC-2119 MUST/SHOULD` | **Rationale nodes** — direct analog of Graphify's WHY-node feature | 100% |

**Design point worth stealing outright:** Graphify's promotion of `# WHY:` comments and ADRs to first-class nodes is its highest-leverage feature per line of code. In text corpora the equivalents are: decision records, changelog entries, RFC normative keywords, meeting-minute action items, PR/issue rationale, contract recitals ("WHEREAS..."), and policy justification clauses. Detect these with a rule pack and give them a dedicated node label `Rationale` with an `applies_to` edge. This is what lets the downstream agent answer *why*, not just *what*.

### 4.2 Output of L1

A **structural spine graph**: typically 30-50% of your final edge count, built in seconds, with confidence `EXTRACTED` and 100% provenance. If everything downstream fails, this alone is still a useful product.

---

## 5. Layer 2 — Linguistic Substrate

All local, all CPU-feasible, all deterministic at fixed weights.

| Component | Recommended | Notes |
|---|---|---|
| Sentence segmentation | `pysbd` or spaCy `senter` | Abbreviation-safe; naive `.split('.')` costs you ~3% F1 downstream. |
| Tokenization + POS + dependency parse | spaCy (`en_core_web_trf` for quality, `_sm` for speed) or **Stanza** for 70+ languages | Dependency arcs are how you do syntactic OpenIE cheaply. |
| **Coreference resolution** | `fastcoref`/`LingMess`, or `maverick-coref` (2024, SOTA-competitive, fast) | **This is the highest-ROI component in the entire stack.** Without it "the company", "it", "they" fragment your entity nodes and destroy multi-hop recall. Run it at *document* scope, not chunk scope. |
| Discourse / rhetorical structure | Optional: RST parser, or lightweight connective detection (`however`, `therefore`, `because`) | Gives you `CONTRASTS_WITH` / `CAUSES` / `SUPPORTS` edges — cheap semantic value. |
| Temporal expression normalization | **HeidelTime** or `SUTime`, plus `dateparser` | Resolves "last quarter", "two weeks ago" against a document reference time `t_ref`. Mandatory for the bi-temporal model in §7. |
| Numeric/unit normalization | `pint`, `quantulum3` | "$1.2M", "1,200,000 USD" → canonical measure objects. |
| Negation & modality | NegEx-style rule pack + hedge lexicon | Prevents the classic failure: extracting `X CAUSES Y` from "X does not cause Y". Store as edge attributes `polarity`, `modality`. |

**Engineering note:** run L2 once per document and cache by `doc_id + model_hash`. Coref is the slowest piece; batch it and consider a length cap with sliding windows for very long docs.

---

## 6. Layer 3 — Encoder-Based Information Extraction (The Core Bet)

### 6.1 Why encoders, not LLMs

| Property | Autoregressive LLM extraction | Encoder IE (GLiNER family) |
|---|---|---|
| Determinism | Poor even at T=0 (batching/kernel nondeterminism) | Effectively deterministic |
| Throughput | ~1 chunk / 1-3 s / call | 100s of chunks/s batched on GPU; workable on CPU |
| Cost model | Linear in tokens × price | One-time model download |
| Data egress | Leaves the machine (unless self-hosted) | Never leaves |
| Schema control | Prompt-dependent, drifts | Label set is an explicit runtime argument |
| Recall on novel/abstract relations | Higher | Lower |

The published GLiNER-Relex work (2026) makes exactly this argument for GraphRAG: current GraphRAG implementations rely on LLMs for extraction, which introduces significant computational cost at scale, and an encoder-based joint model is a substantially faster alternative that enables KG construction over large corpora inside tighter time and cost budgets. Independent work on production GraphRAG has shown that careful engineering of classical NLP techniques can match LLM-based approaches while remaining cost-effective and domain-adaptable at scale.

### 6.2 Concrete model stack

- **NER (zero-shot, arbitrary label set):** GLiNER (`urchade/gliner_*`, and the multi-task / bi-encoder variants). It runs on CPU and consumer hardware and is competitive with far larger models on zero-shot NER benchmarks. You pass the entity types in at inference time — this is what makes your tool domain-agnostic without retraining.
- **Joint NER + RE:** `gliner-relex` — entities and relation triplets in a **single forward pass** (`return_relations=True`). This is your default extraction call.
- **Relation classification over given pairs:** GLiREL, when you already have entity spans and want only the predicate.
- **Document-level RE (cross-sentence):** GLiDRE-class models — needed because a large fraction of real relations span sentences.
- **Entity linking (optional):** ReLiK for retrieve-and-read linking to a canonical inventory if you have one (Wikidata, an internal ontology).

### 6.3 Schema strategy — the decision that determines whether your graph is useful

Three modes; support all three, default to (B).

- **(A) Schema-free / OpenIE.** Extract raw `(subject, predicate, object)` with the surface predicate as the relation type. Maximum recall, maximum mess — you get 4,000 distinct predicates that mean 12 things. This is what HippoRAG-style systems do, and they compensate at retrieval time with PPR rather than at schema time.
- **(B) Schema-guided with induced schema (recommended default).** Run a cheap pass over a sample of the corpus → cluster candidate types/predicates by embedding → propose a schema of ~20-60 entity types and ~30-80 relation types → freeze it in `schema.yaml` → run full extraction constrained to that schema. Reproducible, inspectable, editable by the user, and this file becomes the artifact users tune.
- **(C) User-supplied ontology.** Accept SHACL/OWL-lite or a plain YAML schema. Validate extractions against domain/range constraints and *reject* type-violating triples (this alone kills a large class of hallucinated edges).

**Predicate canonicalization** (needed for A and B): embed predicate surface forms with a sentence encoder, cluster (HDBSCAN or agglomerative with a tuned threshold), pick the medoid as canonical, and keep the surface form as `edge.surface_predicate`. Never throw away the surface form — it's evidence.

### 6.4 The confidence taxonomy (extend Graphify's two tiers to four)

| Tag | Meaning | Produced by |
|---|---|---|
| `STRUCTURAL` | Read directly from machine-readable structure. Cannot be wrong unless the parser is. | L1 |
| `EXTRACTED` | Stated explicitly in the text; the exact supporting span is stored. | L2/L3 |
| `INFERRED` | Derived by the engine — coreference merges, transitive closure, entity resolution, temporal ordering, alias propagation. Deterministic rule, not stated in text. | L2/L5/L7 |
| `GENERATED` | Produced by an LLM (summaries, abstractions, community labels, rationale synthesis). Never treated as evidence. | L4 |

Every edge additionally carries a **numeric** `confidence ∈ [0,1]` and `evidence_count` (how many independent chunks assert it). Repetition across independent documents is your single best precision signal — surface it.

**Rule:** the retrieval layer must be able to filter by tag. An agent asking "what does the contract actually say" should be able to request `STRUCTURAL|EXTRACTED` only.

---

## 7. Layer 4 — The Optional LLM Pass (Narrow and Cacheable)

Reserve the LLM for things encoders genuinely cannot do. Everything here is opt-in, cached by `blake3(prompt || model_id || input)`, and tagged `GENERATED`.

1. **Rationale synthesis.** Convert detected decision/justification blocks into structured `Rationale` nodes: `{decision, alternatives_considered, constraints, supersedes}`.
2. **Abstraction/summary nodes.** RAPTOR-style hierarchical summarization over communities so that "what is this corpus about" is answerable without reading 400 chunks.
3. **Community naming.** (But see §8.3 — do this without an LLM first; Graphify's "auto-labels without an LLM" claim is a differentiator worth preserving.)
4. **Triple filtering / verification.** HippoRAG 2 uses online LLM-based triple filtering to improve precision; use it as an *optional recall-to-precision converter* on low-confidence edges only.
5. **Schema induction** (mode B above).
6. **Hard-case entity matching.** Use LLMs only on the ambiguous band of ER pairs (§8), never on the whole cross-product.

**Cost control:** hard budget in `config.yaml` (`llm.max_calls`, `llm.max_tokens`), a dry-run mode that prints the projected cost, and a `--no-llm` flag that must produce a fully functional graph.

---

## 8. Layer 5 — Entity Resolution & Canonicalization

This is where naive text-KG projects die. You will produce `Acme Corp`, `Acme Corporation`, `ACME`, `the company`, and `it` as five nodes, and your graph becomes useless.

The canonical architecture is **three layers, each with its own failure mode**: blocking (poor blocking → false negatives at scale), scoring (weak scoring → noisy candidates), clustering (bad clustering → fragmented or over-merged nodes that corrupt graph structure).

### 8.1 Blocking (reduce the O(n²) cross-product)

Combine, then union the candidate sets:
- **Deterministic keys:** normalized name, first-3-tokens, acronym expansion, phonetic (Double Metaphone / Beider-Morse for names).
- **Sorted-neighbourhood** with a sliding window over a sort key.
- **ANN/embedding blocking:** encode mention strings + local context, HNSW top-k. `BlockingPy` (2026) shows ANN blocking used together with Splink captures comparison pairs deterministic blocking misses.
- **Type gating:** never compare a `Person` mention to an `Organization` mention (unless your schema allows role ambiguity).

Target: recall ≥ 0.99 on true pairs at ≤ 1e-4 of the full cross-product.

### 8.2 Scoring

- **Probabilistic (Fellegi-Sunter)** via **Splink** — MIT-licensed, runs on DuckDB (so it stays in-process and local), EM-trained `m`/`u` values, handles 100M+ records; capable of linking a million records on a laptop in roughly a minute. This is the right default: it's unsupervised, explainable (match weights per comparison), and produces calibrated probabilities.
- **Feature set:** Jaro-Winkler/token-set on names, embedding cosine on mention context, **relational features** (do the two candidates share neighbours in the graph? — this is the graph-native signal that generic ER tools lack), co-occurrence in the same document, type agreement, temporal compatibility.
- **Hard band → optional LLM adjudication.** Only pairs with `0.35 < p < 0.75` go to an LLM; recent entity-matching literature (Peeters/Bizer line of work) shows LLMs are strong here but you cannot afford them on the full candidate set.

### 8.3 Clustering

- Do **not** use naive connected components on the match graph — one bad edge merges two galaxies (the classic over-merge catastrophe).
- Use **correlation clustering** / weighted-CC with a resolution parameter, or connected components *followed by* a **cluster-cohesion check** (intra-cluster density, diameter cap) that splits suspicious clusters.
- Emit `SAME_AS` edges rather than destructively merging. Keep every original mention node; the canonical entity is a **new node with `HAS_MENTION` edges**. This makes ER reversible, auditable, and tunable at query time — a huge operational advantage and the correct answer to G1 and G3.

### 8.4 Metrics to track
Pairwise P/R/F1, plus cluster-level **B-cubed** and **CEAF** (pairwise metrics lie about over-merging). Ship a `textgraph er audit` command that samples merges for human review.

---

## 9. Layer 6 — Graph Model, Provenance, and Storage

### 9.1 Node & edge schema

**Node labels (core set):**
```
Document, Section, Chunk, Sentence          # structural
Entity(canonical), Mention                  # semantic
Claim/Fact                                  # reified triple
Rationale, Decision, Requirement            # rationale layer
Event, TimeExpression, Measure              # temporal/numeric
Community, Summary                          # derived
Source                                      # provenance root
```

**Reify your relations.** Instead of a bare edge `Acme --ACQUIRED--> Beta`, create a `Claim` node with `subject`, `predicate`, `object`, plus `confidence`, `polarity`, `modality`, `t_valid`, `t_invalid`, `source_spans[]`, `extractor_version`. Then materialize a *derived* direct edge for fast traversal. Reification costs storage and buys you: contradiction handling, multi-source evidence aggregation, temporal validity, and honest provenance. Non-negotiable for a serious system.

### 9.2 Bi-temporal modeling (steal this from Zep/Graphiti)

Track **four timestamps** per fact:
- `t_valid`, `t_invalid` — when the fact held true in the world (event time).
- `t_created`, `t_expired` — when your system learned/retired it (ingestion time).

When a new fact temporally contradicts an existing one, you **invalidate rather than delete**: set the old edge's `t_invalid` to the new edge's `t_valid`. This is exactly how Graphiti handles dynamic updates via temporal extraction and edge invalidation, and it is what lets an agent answer "what did we believe in March, and when did that change?" A standard KG treats facts as timeless; a temporal one tracks how facts change while preserving history.

For your corpus this maps to: contract amendments, spec revisions, policy updates, changelog entries, retracted statements, and superseded meeting decisions. It is one of the most differentiating features you can ship, and it is why LongMemEval's *knowledge update* category is where non-temporal systems collapse.

### 9.3 Storage decision

| Option | Verdict for you |
|---|---|
| **NetworkX + on-disk JSON/Parquet** | Correct for v0.1. Graphs under ~5M edges fit in RAM; Leiden and PPR run fine. Zero install friction — matches Graphify's `pipx install` ergonomics. |
| **Kuzu** | Technically ideal (embedded, Cypher, columnar, vectorized, HNSW vector index, built-in PageRank/shortest-path) — but **the repo was archived in October 2025 after Apple acqui-hired the team.** Existing releases work; no new development. Do not build a product on it in 2026. |
| **LadybugDB** | The active community successor to Kuzu; adds multi-label nodes and direct attach of Arrow/DuckDB/Parquet without ingest. Watch it; strong candidate for v1.0 embedded backend. |
| **FalkorDB** | Redis-based, fast, Cypher, good for multi-tenant many-small-graphs. Server process required. |
| **Neo4j** | Best tooling and ecosystem; heavyweight for a CLI tool. Offer as an optional backend. |
| **DuckDB + recursive CTEs** | Underrated. You already need DuckDB for Splink. Store nodes/edges as Parquet-backed tables, do traversal via recursive CTE, and you get a single-dependency, columnar, zero-server stack. **Strong pragmatic choice.** |

**Recommendation:** `NetworkX` in-memory for compute + **DuckDB/Parquet as the on-disk source of truth**, with a pluggable `GraphStore` interface so LadybugDB/Neo4j/FalkorDB drop in later. Ship `graph.json` regardless (it's the agent's contract).

---

## 10. Layer 7 — Graph Analytics

### 10.1 Community detection — Leiden

Use Leiden, not Louvain. Louvain can produce **internally disconnected communities**; Leiden guarantees well-connected communities and is faster in practice. Implementations: `leidenalg` (+`python-igraph`), or `graspologic`'s `hierarchical_leiden` (what Microsoft GraphRAG uses, and it gives you a hierarchy for free).

Engineering details that matter:
- **Fix the seed.** Leiden is randomized; without `seed=` you break G1.
- **Resolution sweep.** Run γ ∈ {0.5, 1.0, 1.5, 2.0} and pick by modularity stability, or expose the hierarchy directly so users can zoom.
- **Edge weights** should be `confidence × log(1 + evidence_count)`, not 1.0. This is a large quality win and most implementations skip it.
- **Hierarchical output**: `community_level_0 ⊃ level_1 ⊃ ...` — the agent can then answer questions at the right granularity.

### 10.2 Community labeling without an LLM

Graphify's "auto-labels without needing an LLM" is achievable and worth replicating:
1. Take all mention strings + section headings in the community.
2. Compute **c-TF-IDF** (class-based TF-IDF, from BERTopic): term frequency within the community vs. across all communities.
3. Take top-k terms, then apply **MMR** to reduce redundancy.
4. Label = top 2-3 terms, plus the highest-centrality entity name in the community.

Optionally upgrade to `KeyBERT`-style embedding-based keyphrase ranking. Fall back to LLM naming only under `--llm`.

### 10.3 "God nodes" and structural insight

- **Degree**, **weighted degree**, **PageRank**, and critically **betweenness centrality** (approximate via Brandes with k-sampling on large graphs — exact is O(VE)).
- **God nodes** = top percentile by PageRank *and* betweenness. Flag them: they're either genuinely central concepts or **entity-resolution over-merge bugs**. Ship them as a diagnostic, not just a feature.
- **Bridges / structural holes**: edges whose removal disconnects communities. These are your "surprising structural connections" for the report — the single most impressive thing in `GRAPH_REPORT.md`.
- **Orphans and weak components**: content that connects to nothing. Usually a parsing failure. Report it.
- **Contradiction detection**: pairs of `Claim` nodes with the same `(subject, predicate)`, incompatible objects, and overlapping validity intervals. Surface as `CONTRADICTS` edges. Very high user value.

### 10.4 Pathing

- Shortest path: bidirectional BFS on the unweighted graph; Dijkstra with `weight = -log(confidence)` for a **maximum-likelihood path** (this is the right formulation — the most probable explanatory chain, not the shortest hop count).
- **k-shortest paths** (Yen's) so the agent sees alternative explanations.
- Cap path length at 5-6 hops; beyond that, paths are noise.
- Return paths as **narrated evidence chains** with each hop's supporting span — this is what makes the agent's answer verifiable.

---

## 11. Layer 8 — The Retrieval Engine

This is what actually determines your benchmark numbers. Graph construction is table stakes; retrieval is the product.

### 11.1 Adopt the HippoRAG 2 architecture as your backbone

The strongest published design for exactly your problem:
- A **dual-node graph**: phrase/entity nodes *and* passage nodes in one graph, with edges connecting passages to the entities they mention.
- Query → seed scoring: retrieve relevant triples and passages by embedding similarity to build a **personalization vector**.
- Run **Personalized PageRank** over the normalized adjacency matrix, solved by power iteration, seeded by that vector.
- Top-ranked passage nodes become the context for the reader.

Why this over pure Cypher/traversal: PPR is a *soft, weighted, multi-hop* traversal that degrades gracefully when the graph is imperfect — and your graph will be imperfect. It also unifies dense and sparse retrieval rather than choosing.

PPR is also cheap and cacheable: precompute the normalized adjacency once; power iteration on a few million edges takes milliseconds. Note the known limitation to design around: standard HippoRAG's transition matrix is fixed at index time, so edge relevance is context-independent — consider **query-conditioned edge reweighting** (boost edges whose predicate embedding matches the query intent) before running PPR. This is a genuine, publishable improvement and a differentiator.

### 11.2 Hybrid scoring (all three, always)

```
score = w1·BM25(chunk) + w2·cos(query, chunk_emb) + w3·PPR(chunk) + w4·structural_prior
```
Fuse with **Reciprocal Rank Fusion** rather than tuned weights — RRF is robust and needs no calibration. Then **rerank** the top ~50 with a cross-encoder (`bge-reranker-v2-m3` is the community default and runs locally).

### 11.3 Dual-level retrieval (LightRAG's contribution)

Route by query type:
- **Local/specific** ("what did the Q3 contract say about termination") → entity-anchored, low-hop, high-precision.
- **Global/abstract** ("what are the main themes across these 400 documents") → community summaries, not chunks. This is query-focused summarization; flat vector retrieval simply cannot answer it, which is the original GraphRAG result.

Implement a lightweight **query router** (a classifier or a few heuristics: presence of named entities, question words, superlatives, aggregation verbs) that picks the mode — or runs both and fuses.

### 11.4 Query surface for the agent

Expose these as tools (§12), not as a Cypher prompt. Text2Cypher is a liability: it hallucinates schema and fails silently.

| Tool | Signature | Returns |
|---|---|---|
| `search` | `(query, mode=auto\|local\|global, k, min_confidence, tags[])` | ranked chunks + entities + citations |
| `neighbors` | `(entity, hops=1, edge_types[], direction)` | typed adjacency with evidence |
| `path` | `(from, to, k=3, max_hops=5)` | k evidence chains |
| `why` | `(entity_or_claim)` | attached `Rationale`/`Decision` nodes |
| `timeline` | `(entity, from, to)` | bi-temporal fact history incl. invalidations |
| `contradictions` | `(scope)` | conflicting claim pairs |
| `communities` | `(level, filter)` | labeled clusters + summaries |
| `stats` | `()` | god nodes, orphans, coverage, health |

Every response is **budgeted** (`max_tokens`) and every fact carries `[doc:span]` citations. Design the output format for an LLM reader: compact, deduplicated, no prose padding.

---

## 12. Layer 9 — Artifacts & the Skill Surface

### 12.1 `textgraph-out/`

```
textgraph-out/
  graph.json          # the agent's contract — canonical, versioned, sorted
  graph.parquet/      # nodes.parquet, edges.parquet, claims.parquet (query-efficient)
  graph.html          # single-file interactive viz
  GRAPH_REPORT.md     # human/agent-readable orientation
  schema.yaml         # induced or supplied schema — user-editable
  manifest.json       # config hash, model versions, timings, costs, coverage stats
  .cache/             # content-addressed intermediate artifacts
```

**`graph.json` schema (versioned, `schema_version` at root):**
```json
{
  "schema_version": "1.0",
  "manifest": { "config_hash": "...", "models": {...}, "built_at": "..." },
  "nodes": [{ "id","label","name","aliases":[],"props":{},
              "centrality":{"pagerank":0.0,"betweenness":0.0},
              "community":{"0":3,"1":17},
              "mentions":[{"doc_id","span":[s,e]}] }],
  "edges": [{ "id","src","dst","predicate","surface_predicate",
              "tag":"STRUCTURAL|EXTRACTED|INFERRED|GENERATED",
              "confidence":0.0,"evidence_count":1,
              "polarity":"pos|neg","modality":"asserted|hedged",
              "t_valid":null,"t_invalid":null,
              "source_spans":[{"doc_id","span":[s,e]}] }],
  "communities": [{ "level","id","label","members":[],"summary":null }],
  "documents": [{ "doc_id","path","title","lang","hash","chunk_count" }]
}
```
Sort every array by a stable key and serialize with sorted object keys — this is what makes byte-identical rebuilds (G1) real and makes `git diff` on the graph meaningful.

### 12.2 `graph.html`

Single self-contained file, no CDN (local-first). Use **Cosmograph** or `sigma.js`+`graphology` (WebGL) rather than D3 force layout — D3 dies above ~5k nodes. Precompute the layout server-side (ForceAtlas2 in `graphology` or `graph-tool`) and ship coordinates; client-side layout of a large graph is a bad experience. Features: filter by tag/confidence, color by community, search, click-through to source spans, path highlighting.

### 12.3 `GRAPH_REPORT.md`

The orientation document. Structure it as: corpus stats → top communities with labels and sizes → god nodes → **surprising bridges** → detected contradictions → temporal hot spots (what changed most) → coverage gaps/orphans → **10 suggested questions the graph can answer well**. That last section is what makes the agent immediately effective.

### 12.4 Skill packaging

- **Primary:** an MCP server exposing the tools in §11.4. This works across Claude Code, Cursor, Codex, and Gemini CLI without per-host code.
- **Secondary:** a `SKILL.md` + CLI (`textgraph build`, `textgraph query`) for hosts that use file-based skills. Keep `SKILL.md` short and instructional: when to invoke, which tool for which question shape, how to read confidence tags.
- **Install:** `uv tool install textgraph` / `pipx install textgraph`. Python 3.11+. Keep the default install dependency-light; put heavy models behind extras (`textgraph[full]`, `textgraph[ocr]`).

---

## 13. Incremental Updates

Full rebuilds are the reason tools like this get abandoned. Design for incrementality from day one.

1. **Content-addressed everything.** `doc_id`, `chunk_id`, `extraction_id = blake3(chunk_id || model_hash || schema_hash)`.
2. **Dirty-set propagation.** Changed doc → changed chunks → invalidated extractions → affected canonical entities → affected communities.
3. **Locality of re-analysis.** ER only needs to re-run over blocks touching the dirty entities. Communities: run Leiden on the affected subgraph with the rest frozen as a coarsened supernode, then a periodic full recompute (nightly / every N updates) to prevent drift. PPR needs only an adjacency refresh.
4. **Never destructively delete.** Retracted facts get `t_invalid` set. The graph is append-mostly, which also makes it crash-safe.
5. **Watch mode.** `textgraph watch` with a filesystem watcher + debounce for live corpora.

Current systems largely require batch reprocessing when documents change; incremental graph update is an open research area — building it well is a genuine competitive advantage, not a nice-to-have.

---

## 14. Evaluation

Do not ship benchmark numbers you can't reproduce. Build the harness before the features.

### 14.1 Extrinsic (end-to-end QA)

| Benchmark | What it tests | Notes |
|---|---|---|
| **LoCoMo** | 1,540 questions; single-hop, multi-hop, open-domain, temporal over multi-session dialogues (~600 turns, ~32 sessions each) | Widely reported, so good for comparability. Two known limitations: modest context length by 2026 standards and no explicit knowledge-update scoring. A baseline, not a sufficient bar. Also be aware the community has flagged evaluation-harness inconsistencies across published LoCoMo numbers — publish your exact harness. |
| **LongMemEval / LongMemEval-S** | 500 questions across six categories including **knowledge update** and multi-session recall; the -S setting pairs each question with ~115k tokens of history | This is where your bi-temporal model should shine. Reported points of reference: Zep/Graphiti ~71.2% (gpt-4o); several 2026 systems report 94-95%. |
| **BEAM** | 1M and 10M token scales | Designed so no current memory architecture saturates it. The honest benchmark; report it even if the number is low. |
| **MuSiQue / 2WikiMultihopQA / HotpotQA** | Multi-hop associativity | Directly comparable to HippoRAG 2 ablations. |
| **NarrativeQA / LV-Eval** | Sense-making over long context | Where graph structure beats flat retrieval. |

**Always report accuracy paired with tokens-per-query and p50/p95 latency.** A benchmark number without its token cost is marketing. Pair a single-session score with a multi-session one.

### 14.2 Intrinsic (graph quality — this is what you actually debug against)

- **Triple precision:** stratified sample, human/LLM-judge verification against the cited span. Report per confidence tag.
- **ER quality:** B-cubed P/R/F1, over-merge rate, fragmentation rate.
- **Coverage:** % of sentences contributing ≥1 edge; % of documents connected to the main component.
- **Provenance integrity:** 100% of non-`GENERATED` edges must resolve to a valid span whose text still hashes correctly.
- **Determinism test (CI):** build twice, assert `graph.json` byte-equality. This one test protects your whole value proposition.
- **Graph health:** degree distribution (a power law with a fat head usually means over-merging), modularity, component count, orphan rate.

### 14.3 Ablations to run and publish

Structural-only (L1) vs +encoder IE vs +coref vs +ER vs +LLM pass; PPR on vs off; reranker on vs off; chunk size sweep; schema-free vs schema-guided. These ablations *are* your technical marketing, and they tell you where to spend engineering time.

---

## 15. Performance Engineering

- **Parallelism:** L0/L1 are embarrassingly parallel per document (`multiprocessing`); L2/L3 are batched GPU/CPU inference (`torch.inference_mode`, ONNX Runtime or OpenVINO for CPU, dynamic int8 quantization for GLiNER — typically 2-4× throughput at ~1% F1 loss).
- **Backpressure:** stream documents through a bounded queue; never materialize the whole corpus.
- **Embeddings:** one model for everything (`bge-m3` — multilingual, 8k context, dense+sparse+colbert in one model). Store as `float16` in a Parquet/`usearch`/`hnswlib` index. Do not run three embedding models.
- **Memory:** for >10M edges, move from NetworkX to `scipy.sparse` CSR + `igraph` for algorithms; NetworkX's per-node dicts are the bottleneck long before the algorithms are.
- **Target budgets (state them publicly, hold yourself to them):** ~1M words ⇒ L0+L1 under 60s, full local pipeline under 15 min on a laptop CPU, under 3 min on a consumer GPU, incremental single-doc update under 5s.

---

## 16. Failure Modes (and the mitigation you must build)

| Failure | Symptom | Mitigation |
|---|---|---|
| Entity over-merge | One "god node" with 40% of edges | Cluster cohesion checks; ER audit command; god-node diagnostic |
| Entity fragmentation | Same concept as 6 nodes; multi-hop recall collapses | Better blocking recall; coref at doc scope; alias propagation |
| Predicate explosion | 4,000 predicates, none reusable | Predicate canonicalization + schema mode B |
| Negation/hedging inversion | Graph asserts the opposite of the text | NegEx + modality attributes; never drop polarity |
| Coref failure across long docs | Pronoun-heavy text yields empty graphs | Document-scope coref, sliding windows, report coref coverage |
| Chunk-local myopia | Cross-chunk relations never found | Overlapping extraction windows; document-level RE model; cross-chunk augmentation pass |
| Hallucinated edges (LLM pass) | Unverifiable claims | Span-grounding requirement: any `GENERATED` edge without a resolvable span is discarded |
| Temporal contradiction | "CEO is X" and "CEO is Y" both live | Bi-temporal invalidation + `contradictions` tool |
| Silent OCR garbage | Nonsense entities | Confidence downgrade on `ocr:true`; language-model perplexity gate on extracted spans |
| Prompt injection via corpus | A document says "ignore previous instructions" | Treat all corpus text as data; never interpolate raw corpus text into system-level positions; sanitize in tool outputs |
| Benchmark overfitting | Great LoCoMo, bad in production | Hold out an internal corpus; report BEAM |

---

## 17. Build Roadmap

**Phase 1 — Structural spine (2-3 weeks).** L0 + L1 + NetworkX + `graph.json` + `graph.html` + `GRAPH_REPORT.md` + CLI. Zero models. Ship it. This is already useful for documentation sets, wikis, and spec corpora, and it validates your artifact contracts.

**Phase 2 — Encoder IE (3-4 weeks).** spaCy/Stanza + coref + GLiNER-relex + predicate canonicalization + the four-tier confidence tags. Now it's a knowledge graph.

**Phase 3 — Entity resolution (2-3 weeks).** Blocking + Splink + non-destructive `SAME_AS` + ER audit + B-cubed metrics. Quality jumps here more than anywhere else.

**Phase 4 — Retrieval (3-4 weeks).** Dual-node graph, PPR, hybrid + RRF + reranker, query router, MCP server with the eight tools. Now agents can use it. **Benchmark here.**

**Phase 5 — Temporal + incremental (3-4 weeks).** HeidelTime, bi-temporal edges, invalidation, contradictions, dirty-set incremental rebuild, watch mode. This is your differentiation against every flat-RAG competitor.

**Phase 6 — Optional LLM layer + polish.** Rationale synthesis, hierarchical summaries, schema induction, hard-case ER adjudication — all behind `--llm`, all cached, all tagged `GENERATED`.

---

## 18. Where You Can Genuinely Beat the Field

Not "another GraphRAG." Pick two or three of these and go deep:

1. **Byte-identical reproducibility** with a CI test proving it. Nobody in this space offers it, and it's exactly what enterprise/regulated buyers need.
2. **Provenance to the byte range on every non-generated edge**, with a verification command that re-hashes spans. Auditability as a product feature.
3. **Bi-temporal + contradiction detection over documents** (not just conversations). Contract amendments, spec revisions, policy changes — a large, underserved market.
4. **Encoder-only extraction as the default**, with published ablations showing how close it gets to LLM extraction at ~1/100th the cost. This is the Graphify "no LLM for code" story, correctly translated to text.
5. **Query-conditioned PPR** — fixing the known static-transition-matrix limitation of HippoRAG-family retrieval.
6. **The `why` tool.** Rationale nodes over decision records are the single most agent-useful, least-replicated feature in Graphify. In text corpora nobody is doing this well.

---

## 19. Reading List (prioritized)

**Read first, in this order:**
1. Edge et al., *From Local to Global: A Graph RAG Approach to Query-Focused Summarization* (MS GraphRAG) — the community-summary paradigm.
2. Gutiérrez et al., *From RAG to Memory: Non-Parametric Continual Learning for LLMs* (HippoRAG 2, ICML 2025, arXiv 2502.14802) — **your retrieval blueprint**.
3. Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory* (arXiv 2501.13956) — **your temporal model**.
4. Guo et al., *LightRAG* (arXiv 2410.05779) — dual-level retrieval.
5. Traag, Waltman, van Eck, *From Louvain to Leiden: guaranteeing well-connected communities* (2019).

**Then:**
6. Min et al., *Towards Practical GraphRAG: Efficient KG Construction and Hybrid Retrieval at Scale* (arXiv 2507.03226, CIKM'25) — the classical-NLP-matches-LLM result.
7. Zaratiana et al., *GLiNER* (2023) + *GLiNER multi-task* (2406.12925) + *GLiNER-Relex* (2605.10108).
8. Papadakis et al., *Blocking and Filtering Techniques for Entity Resolution: A Survey* (ACM CSUR 2020); Splink docs.
9. Sarthi et al., *RAPTOR* (2401.18059) — hierarchical summary trees.
10. Ash et al., *SLIDE: Sliding Localized Information for Document Extraction* (2503.17952) — contextual chunking for KG construction.
11. Maharana et al., *LoCoMo* (2024); Wu et al., *LongMemEval* (ICLR 2025) + *LongMemEval-V2* (2605.12493).
12. *Beyond Chunk-Local Extraction: Cross-Chunk Graph Augmentation for GraphRAG* (2605.28004) — directly addresses your chunk-myopia problem.

**Tooling docs:** Docling, spaCy/Stanza, fastcoref/maverick-coref, Splink, BlockingPy, leidenalg/graspologic, graphology/sigma.js, DuckDB, LadybugDB, bge-m3 + bge-reranker-v2-m3, Drain3, HeidelTime.

---

## 20. One-Paragraph Positioning

*TextGraph turns any body of text — documents, specs, contracts, transcripts, logs, threads, wikis — into a queryable knowledge graph with byte-level provenance on every claim. Extraction runs entirely on your machine using deterministic structural parsers and encoder-based information extraction models; no LLM calls are required and your text never leaves your machine. Every edge is tagged STRUCTURAL, EXTRACTED, INFERRED, or GENERATED, carries the exact source span that supports it, and is versioned bi-temporally so you can ask not just what is true, but what was true, when it changed, and why. Exposed as an MCP skill, it gives coding and research agents multi-hop paths, community structure, contradiction detection, and rationale — instead of a bag of semantically similar chunks.*
