# TextGraph

> Turn a pile of case documents into a **queryable knowledge graph with byte-level provenance on every claim** — local-first, deterministic, and agent-legible.

TextGraph is built to help investigators make sense of **financial-crime and technical-crime** evidence: filings, contracts, wire-transfer logs, SARs, memos, chat/email exports, and reports. It ingests that corpus and emits a structured, versioned graph that shows **who is connected to whom, through what, and — crucially — *why*** — with every edge carrying the exact source span that supports it, so a finding can be re-verified and stands up to audit.

It is the natural-language successor to [**llm-wiki**](https://github.com/krishddd/llm-wiki): where `llm-wiki` gave an agent cited, streaming answers over Wikipedia, TextGraph generalizes that to **any textual corpus** and produces a graph an agent can traverse — multi-hop relationship discovery, contradiction detection, temporal reasoning, and provenance-backed retrieval — not just a stream of prose.

## Who it's for

- **Financial-crime analysts** — trace structuring/layering, link cases through a shared beneficial owner, follow the money across accounts, and answer *why* two cases are related with a cited path.
- **Fraud & technical-crime investigators** — correlate logs, tickets, chat threads, and reports; surface the decision/rationale trail behind an incident.
- **Compliance & audit** — every non-generated claim re-hashes against its source bytes, so evidence is re-verifiable and retained (not silently rewritten).
- **Coding & research agents** — via MCP tools that return bounded, ranked, cited context instead of a bag of similar chunks.

## Supported formats

Investigators don't get clean markdown — they get PDFs, Word docs, and exports. L0 ingests, deterministically:

| Class | Formats | Default install |
|---|---|---|
| Markup / notes | `.md` `.markdown` `.mdx` `.txt` | ✅ built-in |
| Rich documents | `.docx` `.odt` `.rtf` `.html`/`.htm` `.epub` | ✅ built-in (stdlib parsers) |
| Structured data | `.json` `.yaml`/`.yml` `.toml` | ✅ built-in |
| Logs | `.log` (template mining) | ✅ built-in |
| Conversations | `.chat` `.transcript` (speaker turns) | ✅ built-in |
| PDF | `.pdf` | `pip install 'textgraph[ingest]'` (pypdf; Docling for layout/OCR) |

Unknown extensions fall back to plain text; a format needing a missing extra is **skipped with a warning**, never a crash (G2). For rich formats the *extracted* text becomes the canonical document, and every citation still re-verifies against it.

## Quickstart

```bash
uv tool install textgraph        # or: pipx install textgraph
textgraph build ./case-files -o textgraph-out
# → textgraph-out/graph.json, GRAPH_REPORT.md, graph.html, schema.yaml, manifest.json

# Then query the graph directly — bounded, byte-cited answers, no LLM required:
textgraph query   ./case-files "who transferred funds to whom"
textgraph path    ./case-files "Acme Corp" "Gamma Holdings"
textgraph explain ./case-files "Acme Corp"           # cited claims + validity windows
textgraph timeline ./case-files "Acme Corp"          # what was true, and when it changed
textgraph contradictions ./case-files                # conflicting assertions, cited

# Keep the graph in sync with a live case folder (incremental, only re-extracts edits):
textgraph watch ./case-files -o textgraph-out

# ...or explore all eight tools in a local, dependency-free web console:
textgraph console ./case-files          # -> http://127.0.0.1:8765
```

Open `GRAPH_REPORT.md` for orientation (god nodes, communities, contradictions, and **10 questions the graph can answer well**), or `graph.html` for a self-contained, click-to-source-span explorer. Agents drive the same eight typed tools over MCP — see [`textgraph.mcp`](textgraph/mcp/).

## Why it exists

`llm-wiki` proved the value of citation-grounded, MCP-exposed knowledge retrieval. TextGraph extends that tool along three axes:

| llm-wiki | TextGraph |
|---|---|
| Answers over Wikipedia | Ingests **any** textual corpus |
| Streamed prose with sources | **Queryable knowledge graph** with byte-range citations on every edge |
| LLM-in-the-loop | **Zero LLM calls required** — deterministic parsers + encoder IE by default (`--no-llm` always works) |
| Point-in-time answer | **Bi-temporal** — what is true, what *was* true, when it changed, and why |

## The one-paragraph pitch

TextGraph turns any body of text into a queryable knowledge graph with byte-level provenance on every claim. Extraction runs entirely on the user's machine using deterministic structural parsers and encoder-based information-extraction models — no LLM calls are required and text never leaves the machine by default. Every edge is tagged `STRUCTURAL`, `EXTRACTED`, `INFERRED`, or `GENERATED`, carries the exact source span that supports it, and is versioned bi-temporally so an agent can ask not just *what is true*, but *what was true, when it changed, and why*.

## Design goals (non-negotiable)

- **G1 — Determinism.** Same corpus + same version ⇒ byte-identical `graph.json`.
- **G2 — Local-first.** Zero network calls by default; any LLM pass is opt-in.
- **G3 — Provenance.** No assertion without a re-verifiable byte-range citation.
- **G4 — Confidence stratification.** Every edge tagged `STRUCTURAL / EXTRACTED / INFERRED / GENERATED`.
- **G5 — Incrementality.** One changed file never forces a full rebuild.
- **G6 — Agent-legible output.** Bounded, ranked, cited context packs — never raw Cypher.
- **G7 — Bounded, auditable cost.** Per-stage token/time/dollar budgets in a run manifest.

## Architecture at a glance

A strictly bottom-up layer stack. Each layer is a **pure function of the layer below it plus a pinned config hash** — the single property that makes determinism (G1) and incrementality (G5) achievable. `L0 → L1` (the structural spine) is implemented and ships today; the semantic and retrieval layers land in later phases.

```mermaid
flowchart TD
    IN["📄 Case corpus<br/>PDF · DOCX · ODT · RTF · HTML · EPUB<br/>JSON/YAML · logs · chat/email exports"]

    subgraph SPINE["🟢 Structural spine — Phase 1 (zero LLM, deterministic)"]
        direction TB
        L0["L0 · Ingest &amp; Normalize<br/><i>CanonicalDoc = UTF-8 + offset map + block tree</i>"]
        L1["L1 · Deterministic Structure<br/><i>sections, links, definitions, citations,<br/>Rationale &amp; Requirement nodes</i>"]
        L0 --> L1
    end

    subgraph SEM["⚪ Semantic layers — Phase 2+"]
        direction TB
        L2["L2 · Linguistic substrate<br/><i>coref · temporal · negation</i>"]
        L3["L3 · Encoder IE<br/><i>entities + typed relations</i>"]
        L4["L4 · Optional LLM<br/><i>rationale synthesis (opt-in)</i>"]
        L5["L5 · Entity resolution<br/><i>SAME_AS lattice, non-destructive</i>"]
        L2 --> L3 --> L4 --> L5
    end

    subgraph RETR["🟢 Graph &amp; retrieval — Phase 4 (zero LLM, deterministic)"]
        direction TB
        L6["L6 · Claim reification<br/><i>reified Claims + t_valid provenance</i>"]
        L7["L7 · Analytics<br/><i>PageRank · communities · bridges · contradictions</i>"]
        L8["L8 · Retrieval<br/><i>BM25 + Personalized PageRank + RRF</i>"]
        L6 --> L7 --> L8
    end

    L9["📦 L9 · Artifacts + MCP / Skill<br/>graph.json · graph.html · GRAPH_REPORT.md · MCP tools"]

    IN --> L0
    L1 --> L2
    L5 --> L6
    L8 --> L9
    L1 -.->|"ships today (models-free)"| L9
```

## Status

🟢 **Phase 5 complete — bi-temporal graph, persistent storage, and incremental `watch` (L0–L8 + MCP).**

- **L0 ingestion** across markdown, plain text, HTML, DOCX, ODT, RTF, EPUB, JSON/YAML/TOML, logs, and transcripts (PDF behind the `[ingest]` extra), each producing a `CanonicalDoc` + span-carrying block tree + hierarchical chunks.
- **L1 structure parse** (zero models): sections, links, definitions, citations, cross-references, transcript threads, log templates, structured fields, and **Rationale / Requirement nodes** (WHY / DECISION / MUST / SHALL …). Every edge is `STRUCTURAL` with a re-verifiable byte-range citation.
- **L2 + L3 encoder IE** — the build now extracts **entities** (Organization, Person, Money, Account, Date, Email) and **typed relations** (`TRANSFERRED` with amount, `CONTROLS`, `BENEFICIAL_OWNER_OF`, `DIRECTOR_OF`, `ASSOCIATED_WITH`), tagged `EXTRACTED`. Coreference-lite resolves `it`/`the company` to the nearest org (relations so resolved are tagged `INFERRED`), and **negation/modality are preserved** (`did not transfer` → negated; `may be linked` → hedged). The default backend is deterministic and model-free (CPU-only, CI-safe); a GLiNER backend lives behind the `[ie]` extra.
- **L5 entity resolution** — alias entities collapse to one canonical identity: `Acme Corp` / `Acme Corporation` / `ACME` → **"Acme Corporation"**, linked non-destructively via `SAME_AS` (tagged `INFERRED`, reversible, span-cited). Deterministic blocking (suffix-stripped / acronym / token keys) → Jaro-Winkler + **relational shared-neighbour** scoring → complete-linkage clustering that blocks the over-merge catastrophe. `textgraph er audit` surfaces every proposed merge; B-cubed F1 is gated in CI. Splink (Fellegi-Sunter) is the optional `[er]` backend.
- **L6 claim reification** — every relation edge becomes a first-class, citable **`Claim`** node (subject/predicate/object/polarity/modality/confidence) with a shallow temporal window: `t_valid` is grounded to the nearest `Date` in the same sentence (full bi-temporal invalidation is Phase 5). The direct edge is kept, so traversal is unchanged; the Claim is what makes *why* / *timeline* / *contradictions* answerable.
- **L7 analytics** (pure-Python, deterministic) — weighted **PageRank** + **Brandes betweenness**, **label-propagation communities** with automatic c-TF-IDF labels, plus diagnostics folded straight into the graph: centrality/community written onto entity nodes, **god nodes** (central on both measures), **bridges**, orphans, and **contradictions** surfaced as `CONTRADICTS` edges. Leiden is the optional `[graph]` upgrade.
- **L8 retrieval** — the **HippoRAG-style dual-node graph** (entities + `Chunk` passages) powers eight typed, bounded, **cited** tools: `search` (hybrid pure-Python **BM25 + Personalized PageRank fused with RRF**, local/global routing), `neighbors`, `path` (maximum-likelihood, shortest under `-log(confidence)`), `why`, `timeline`, `contradictions`, `communities`, `stats`. Every result is a token-budgeted context pack where each row carries a `[doc:start-end]` byte citation — never raw Cypher (G6).
- **MCP + CLI** — the same `QueryEngine` drives the MCP tool surface (`textgraph.mcp`, stdio server behind the `[mcp]` extra) and three new CLI verbs: `textgraph query`, `textgraph path`, `textgraph explain`.
- **L9 artifacts**: byte-stable `graph.json` (now including Claims, Chunks, centrality/community properties, and CONTRADICTS edges), `GRAPH_REPORT.md` (entities, relationships, resolved SAME_AS clusters, **communities**, **contradictions**, 10 grounded questions), a self-contained `graph.html` explorer, `schema.yaml`, and `manifest.json` (per-layer L0–L8 counts + coref/blocking stats). First retrieval **[benchmark](BENCHMARKS.md)** publishes recall@k / MRR *with* tokens-per-query and latency ("no number without its cost").
- CI gates all of it: lint, strict types, a byte-identical **determinism** gate (models pinned/seeded), 100% edge-provenance re-verification across the full four-tier taxonomy, a B-cubed ER-quality floor, and a tool-only **agent-session** integration test.

```mermaid
flowchart LR
    Q["🔎 agent query"] --> ENG["L8 QueryEngine<br/><i>8 typed tools</i>"]
    subgraph DUAL["Dual-node retrieval graph"]
        direction TB
        CH["Chunk passages<br/><i>BM25 lexical</i>"]
        EN["Entities + Claims<br/><i>Personalized PageRank</i>"]
        CH -- MENTIONS --> EN
    end
    ENG -- lexical --> CH
    ENG -- associative --> EN
    CH & EN --> RRF["Reciprocal Rank Fusion<br/>+ local/global routing"]
    RRF --> OUT["📦 bounded, cited context pack<br/><i>[doc:start-end] on every row</i>"]
```

### What Phase 1 does to each file

```mermaid
flowchart LR
    F["file bytes"] --> DISP{"dispatch<br/>by extension"}
    DISP --> CD["CanonicalDoc<br/>UTF-8 + offset map"]
    CD --> BT["block tree<br/>+ hierarchical chunks"]
    BT --> PARSE["L1 parse_corpus<br/>(zero models)"]
    PARSE --> NODES["Nodes<br/>Document · Section · Chunk<br/>Term · Rationale · Requirement<br/>Participant · Message · Reference"]
    PARSE --> EDGES["Edges — all STRUCTURAL, conf 1.0<br/>CONTAINS · LINKS_TO · DEFINES · CITES<br/>APPLIES_TO · STATES_REQUIREMENT<br/>+ re-verifiable byte-range citation"]
    NODES --> OUT["📦 graph.json · GRAPH_REPORT.md · graph.html"]
    EDGES --> OUT
```

### What you get (example: an AML case)

**The structural spine (L1)** over the `chat` + `adr` fixtures — cited, and already answering *why*:

```mermaid
graph LR
    ALICE(["👤 Alice"]) -->|PARTICIPANT| DOC["📄 case-4471.chat"]
    BOB(["👤 Bob"]) -->|PARTICIPANT| DOC
    M1["💬 'three wire transfers<br/>Acme → Beta'"] -->|SENT_BY| ALICE
    M2["💬 'escalate case-4471'"] -->|SENT_BY| BOB
    M2 -->|REPLIES_TO| M1
    R["🧭 Rationale · WHY<br/>'classic layering'"] -->|APPLIES_TO| M1
    M2 -->|STATES_REQUIREMENT| REQ["⚖️ Requirement<br/>'MUST file a SAR'"]
    DEC["🧭 Rationale · DECISION<br/>'link cases by shared<br/>beneficial owner'"] -->|APPLIES_TO| ADR["📄 adr-0007 · §Decision"]

    classDef doc fill:#2f5d8a,color:#fff,stroke:#1f3d5a;
    classDef who fill:#3f7d4e,color:#fff,stroke:#2a5a38;
    classDef why fill:#8a5a2f,color:#fff,stroke:#5a3a1f;
    classDef req fill:#7a4fa0,color:#fff,stroke:#4a2f70;
    class DOC,ADR doc;
    class ALICE,BOB who;
    class R,DEC why;
    class REQ req;
```

> Edges shown are exactly what L1 emits, each carrying a re-verifiable byte-range citation. `SENT_BY` points message → participant, `PARTICIPANT` participant → document, `APPLIES_TO` rationale → the block it justifies.

**The entities & relationships (L2 + L3)** — now extracted from `wire-transfers.md`. "Acme Corp wired $2,000,000 to Beta Ltd" becomes a real `Organization → TRANSFERRED → Organization` edge:

```mermaid
graph LR
    ACME(["🏢 Acme Corp"]) -->|"TRANSFERRED · $2,000,000"| BETA(["🏢 Beta Ltd"])
    ACME -->|CONTROLS| GAMMA(["🏢 Gamma Holdings"])
    GAMMA -->|BENEFICIAL_OWNER_OF| DELTA(["🏢 Delta Trust"])
    JOHN(["👤 John Doe"]) -->|DIRECTOR_OF| BETA
    BETA -.->|"TRANSFERRED (inferred via 'the company')"| GAMMA
    BETA -.->|"TRANSFERRED (negated)"| OMEGA(["🏢 Omega Bank"])
    ACME -.->|"ASSOCIATED_WITH (hedged)"| SIGMA(["🏢 Sigma Partners"])

    classDef org fill:#2f5d8a,color:#fff,stroke:#1f3d5a;
    classDef person fill:#3f7d4e,color:#fff,stroke:#2a5a38;
    class ACME,BETA,GAMMA,DELTA,OMEGA,SIGMA org;
    class JOHN person;
```

> Solid edges are `EXTRACTED`; dotted are `INFERRED` (coref) or carry a preserved `polarity`/`modality` attribute (negated / hedged) — never silently dropped. Every edge still cites the exact source span. The default extractor is deterministic and model-free; GLiNER (`[ie]`) is a higher-recall drop-in.

> **Phase 3 update:** `Acme Corp`, `Acme Corporation`, and `ACME` now collapse into one canonical **"Acme Corporation"** node via reversible `SAME_AS` links, while `Alpha Bank` stays separate. Run `textgraph er audit ./case-files` to review every proposed merge with its match score.

> **Phase 4 update:** the graph is now queryable. Ask it directly — every answer comes back bounded and byte-cited:
>
> ```bash
> textgraph query   ./case-files "who transferred funds to whom"
> textgraph path    ./case-files "Acme Corp" "Gamma Holdings"   # maximum-likelihood chain
> textgraph explain ./case-files "Acme Corp"                     # cited claims, with t_valid
> ```

> **Phase 5 update:** the graph is now bi-temporal and incremental. Corrections *invalidate* rather than delete — `Acme Corp transferred $1M to Beta Ltd` (2026-05-01) is superseded by a dated correction, its window closed to `[2026-05-01, 2026-06-01)` with a cited `SUPERSEDES` edge, and `textgraph timeline` shows both. `textgraph watch ./case-files` keeps artifacts in sync, re-extracting only edited files; `textgraph build --store g.duckdb` persists the graph so it reloads without a rebuild.

> **Phase 6 (in progress):** the opt-in LLM pass (L4) has landed. It's **off by default** — when enabled it summarizes the graph's communities and tags every summary `GENERATED`, so model output is quarantined and can never be mistaken for a cited fact (and `graph.json` stays byte-identical whenever the LLM is off):
>
> ```bash
> export API_KEY=…                       # read from the env only, never persisted
> export MODEL_BASE_URL=https://…/v1     # OpenAI / vLLM / Ollama — any /chat/completions
> export MODEL_NAME=your-model
> textgraph build ./case-files --llm     # adds GENERATED community summaries
> ```

> **Phase 6 update:** the opt-in LLM pass (L4, `GENERATED`-tagged, off by default) and a dependency-free local **`textgraph console`** web UI have landed — all eight typed tools in the browser, every row cited. Packaging is verified (wheel + `textgraph` entry point).

Next: the v1.0 version bump and release notes — the ship point. See [PLAN.md](PLAN.md) for the roadmap.

## Specification documents

- [`textgraph-engineering-research.md`](textgraph-engineering-research.md) — the primary engineering specification (L0–L9 stack, model choices, storage, retrieval, evaluation).
- `TextGraph_Engineering_Blueprint.pdf` — slide-deck rendering of the architecture (visual cross-check + UI reference).
- `TextGraph Architecture Gap Analysis.docx` — enterprise extension research (GQL surface, vision-native ingestion, fine-grained access control, Graph-of-Thoughts).

## Related work

- [llm-wiki](https://github.com/krishddd/llm-wiki) — the predecessor tool this project extends.
- **Graphify** — the closest prior art (tree-sitter over *code*); TextGraph recovers its guarantees (determinism, locality, provenance, cost linearity) for the domain of arbitrary natural language.

## License

MIT
