# TextGraph vs. Semantica

[Semantica](https://github.com/semantica-agi/semantica) is the closest peer to TextGraph:
both build **auditable, provenance-first knowledge graphs for regulated domains** rather than
black-box RAG. This note is an honest side-by-side — where they agree, where each is stronger,
and what TextGraph added (v3.2) to close the gap on LLM-assisted intelligence.

## Shared philosophy

Both systems reject "embeddings-only" RAG in favour of a typed graph with decision provenance,
conflict handling, and bi-temporal facts. Notably, both expose the same decision-intelligence
API surface — `record_decision` / `trace_decision_chain` / `find_similar_decisions` — and both
export **W3C PROV-O**. The convergence is independent validation that this is the right shape
for compliance-grade AI.

## Side by side

| Dimension | TextGraph | Semantica |
| --- | --- | --- |
| **Determinism** | **Byte-identical `graph.json`, gated in CI.** Diff two runs, reproduce any finding. | Deterministic *reasoning* (Datalog/Rete); build determinism not a stated guarantee. |
| **Provenance** | **Byte-range citation on every non-generated edge, re-hashed against source bytes** (100% re-verify gated). | PROV-O lineage with metadata (confidence, extractor, page) — document/field level. |
| **LLM by default** | **Zero.** LLM is opt-in, quarantined, `GENERATED`-tagged. | LLM optional; broad LiteLLM multi-provider surface. |
| **Extraction** | Rule + GLiNER (deterministic); **opt-in LLM relation enrichment** (v3.2). | NER/relation/event/triplet backends, LLM-assisted. |
| **Retrieval** | BM25 + Personalized-PageRank + **dense embeddings** (v3.2), RRF-fused. | Hybrid dense+sparse over FAISS/Qdrant/Weaviate/Milvus/… |
| **Answers** | Templated + cited by default; **opt-in grounded LLM synthesis** (v3.2). | Rule-engine justifications; explicitly avoids LLM prose for answers. |
| **Graph store** | DuckDB default; **RDF/Turtle export** (loads into Oxigraph/Jena/any SPARQL store); Neo4j design. | Polyglot: RDF (Oxigraph/Jena/…) **and** LPG (Neo4j/Neptune/…), live. |
| **Ontology** | **OWL vocabulary + SHACL shapes export** (induced from the graph) + PROV-O. | OWL generation, SHACL validation, SKOS. |
| **Export formats** | `graph.json`, **RDF/Turtle**, **OWL**, **SHACL**, **PROV-O JSON-LD**, RDF-reified provenance. | RDF, OWL, Parquet, Cypher, JSON-LD, PROV-O. |
| **Reasoning** | Graph-of-Thoughts (complexity-gated), GQL. | Forward chaining, Rete, Datalog, SPARQL. |
| **Footprint** | Dependency-free core (stdlib); everything heavy behind extras. | Broader dependency surface (many backends/providers). |
| **Access control** | Built-in ReBAC/ABAC, security-aware retrieval. | Self-hosted; enterprise data-platform integrations. |

## Where TextGraph is differentiated

- **Byte-identical reproducibility** and **re-hashable byte-span citations** are stronger,
  more falsifiable guarantees than document/field-level provenance. This is the moat.
- **Dependency-free, local-first core** — the whole default pipeline runs CPU-only with no
  API key and no vector database.

## Where Semantica is broader

- **Polyglot storage** (RDF + LPG) and **formal ontology** (OWL/SHACL/SPARQL).
- **Multi-provider LLM** breadth (LiteLLM) and a wider menu of managed vector stores.
- **Formal rule reasoning** (Datalog/Rete) beyond TextGraph's Graph-of-Thoughts.

## What v3.2 added (to be "intelligent" without losing the moat)

TextGraph 3.2 adds LLM-assisted **input** and **output** and **semantic retrieval** — each
**opt-in and quarantined**, so the deterministic-by-default build is untouched:

1. **Dense semantic retrieval** — an OpenAI-compatible `/embeddings` client (local Ollama
   `nomic-embed-text`, vLLM, or OpenAI) or local `sentence-transformers`, cosine-ranked and
   **fused into the existing BM25 + PageRank RRF blend**. Query-time only — never in
   `graph.json`, so determinism holds. Disk-cached, so re-runs are free.
2. **LLM relation extraction (input)** — `build --llm-extract` runs the LLM (default: NVIDIA
   **Nemotron** via vLLM) over chunks to add `GENERATED`-tagged relations the deterministic
   extractors miss, each cited to its chunk and bounded by a call budget.
3. **LLM answer synthesis (output)** — `query --narrate` composes a fluent, **cited** answer
   strictly from the retrieved evidence, tagged `GENERATED`, and instructed to abstain when
   the evidence is insufficient.

The design rule throughout: **the LLM augments, it never becomes the ground truth.** Anything
model-authored is `GENERATED`-tagged and shown next to the re-verifiable citations it was built
from — so TextGraph gains Semantica-class intelligence while keeping the determinism and
byte-level provenance that set it apart.
