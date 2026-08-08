# Running TextGraph

Everything you need to install TextGraph, build a graph from your documents, and explore
it in the interactive UI. The default path is **local-first, deterministic, and needs no
GPU or network** — three small pure-Python packages.

---

## 1. Environment

| | |
|---|---|
| **Python** | 3.11 or newer |
| **OS** | Windows, macOS, or Linux |
| **Hardware** | Any laptop — the default path is CPU-only, no GPU |
| **Network** | None required (nothing leaves your machine unless you opt into the LLM pass) |

Check your Python:

```bash
python --version    # must be 3.11+
```

## 2. Requirements files

| File | What it installs | When you need it |
|---|---|---|
| [`requirements.txt`](../requirements.txt) | Core runtime (3 packages) | **Always** — the UI and the core CLI |
| [`requirements-dev.txt`](../requirements-dev.txt) | Tests, lint, type-check, hooks | Contributing / running the test suite |
| [`requirements-full.txt`](../requirements-full.txt) | All optional extras (vision, security, encoder IE, DuckDB, MCP…) | Only for the heavy opt-in features |

The `pyproject.toml` is the source of truth; these files mirror it for plain `pip`.

## 3. Install

Pick **one** of the two ways.

### Option A — pip + a virtual environment (most common)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
pip install -e .          # installs the `textgraph` command
```

### Option B — uv (fast, what the project is developed with)

```bash
uv sync                   # core
uv sync --extra dev       # + the dev toolchain (to run tests)
# prefix commands with `uv run`, e.g. `uv run textgraph …`
```

Verify the install:

```bash
textgraph version         # prints the version
```

If anything looks off, run the read-only environment health check before filing an issue.
It confirms your Python version, which optional extras are installed, and — the key one —
that this machine produces a **byte-identical `graph.json`** on a tiny build (the same
determinism guarantee CI enforces):

```bash
textgraph doctor
```

`doctor` is read-only (no repairs or writes). Use `--json` as a CI/preflight gate, or
`--check <name>` to run a single check (e.g. `textgraph doctor --check determinism`).

## 4. Build a graph from your documents

Point TextGraph at a folder of documents (Markdown, text, HTML, JSON/YAML, logs, chat
transcripts; PDF with the `ingest` extra). It writes a `textgraph-out/` folder.

```bash
textgraph build ./my-documents -o textgraph-out
```

Out of the box that produces `graph.json` (the byte-stable knowledge graph),
`GRAPH_REPORT.md`, a self-contained **`graph.html`** viewer, `schema.yaml`, and
`manifest.json`. There's a ready-made sample corpus in the repo if you just want to try
it: `tests/fixtures/corpora/docs`.

## 5. Open the interactive UI

The **console** is a local web app over the graph — a clean, spacious viewer that shows
your data points at a glance (entity / relation / community counts), the force-laid graph,
a top-entities-by-importance list, and click-to-inspect cited claims. It's self-contained
(no CDN, no framework) and read-only.

```bash
textgraph console ./my-documents
# or explore a persisted snapshot:  textgraph console snapshot.duckdb
# it prints:  TextGraph console: http://127.0.0.1:8765  (Ctrl-C to stop)
```

Then open **http://127.0.0.1:8765** in your browser. Options: `--port 9000`, `--host 0.0.0.0`.

What you can do in it:

- **Ask** (chat dock at the bottom): type a question in plain English — "how is Acme
  connected to Delta Trust?", "why does Acme matter?", "who transferred funds?". It routes
  to the right graph tool, answers with cited evidence (and, for reasoning questions, a
  collapsible step-by-step chain), and highlights the answer on the graph above. Follow-ups
  work ("why?"). No LLM — the answers are grounded in the graph and fully deterministic.
- **Attach files** (opt-in): start the console with `textgraph console ./docs --allow-ingest`
  and a 📎 button appears in the chat. Drop in a document (`.md`, `.txt`, `.html`, `.json`,
  `.csv`, …) and it is added to the live graph — the file is written into the corpus folder,
  the graph is incrementally rebuilt, and the canvas + stat cards refresh. Without
  `--allow-ingest` the console is strictly read-only.
- **Stat cards** across the top surface the headline numbers (entities, relations,
  communities, time points).
- **Search** entities & passages (top bar, press Enter) — matches highlight on the graph.
- **Click a node** (or a name in *Top entities*) to inspect its cited claims, each with a
  re-verifiable `[doc:start-end]` source pointer and its validity window.
- **Path** mode: click it, then click two nodes to trace the most-trustworthy path between
  them.
- **Communities** panel toggles clusters on/off; **Confidence tags** filter edges by how
  they were derived (STRUCTURAL / EXTRACTED / INFERRED / GENERATED).
- **Time slider** (bottom, when the corpus has dated claims) scrubs the graph through time,
  fading superseded relations.
- **Light / dark** toggle (top-right) — it also follows your system theme.

Prefer no server? The `graph.html` written by `build` is the **same viewer, fully offline**
— just open the file. (Serve it over `http.server` if your browser blocks local-file
scripts.)

## 6. The rest of the CLI (optional)

Every query the UI runs is also a command, over the same graph:

```bash
textgraph query   ./my-documents "who moved the money"
textgraph path    ./my-documents "Acme Corp" "Delta Trust"
textgraph gql     ./my-documents "MATCH (a)-[:CONTROLS]->(b) RETURN a.name, b.name"
textgraph reason  ./my-documents "how is Acme Corp connected to Delta Trust"
textgraph secure  ./my-documents "who moved the money" --policy policy.json --principal alice
textgraph conflicts ./my-documents   # single-truth disagreements, surfaced not merged
textgraph conflicts ./my-documents --resolve voting   # opt-in: pick a winner, supersede losers
textgraph trace-decision ./my-documents "byte-range citations"   # causal lineage of a decision
textgraph find-decisions ./my-documents "why retention changed"  # search decisions by statement
```

### Semantic search + LLM (opt-in, v3.2)

Add a **dense semantic** signal to search (fused with BM25 + PageRank). Point it at a local
Ollama, a vLLM, or OpenAI — the embeddings are cached, and they never touch `graph.json`:

```bash
textgraph query ./docs "systems posing serious risk" --embed openai \
  --embed-model nomic-embed-text --embed-url http://localhost:11434/v1
```

Compose a **grounded, cited** answer from the retrieved evidence with an LLM (tagged
`GENERATED`, abstains when unsupported). The endpoint is read from the environment:

```bash
export MODEL_BASE_URL=... API_KEY=... MODEL_NAME=nvidia/Nemotron-Mini-4B-Instruct
textgraph query ./docs "what obligations apply to high-risk AI" --narrate
```

Enrich the graph with LLM-found relations the deterministic extractors miss (opt-in,
`GENERATED`-tagged, cited to the chunk, budget-bounded):

```bash
textgraph build ./docs --llm-extract -o textgraph-out
```

The rule throughout: **the LLM augments, it never becomes ground truth** — everything
model-authored is `GENERATED`-tagged and shown next to its re-verifiable citations. See
[docs/COMPARISON_SEMANTICA.md](COMPARISON_SEMANTICA.md) for how this compares to Semantica.

Conflicts are **surfaced, never silently merged**. Resolution is opt-in and
non-destructive — losing claims are demoted (`SUPERSEDED_BY`, keeping their citation),
never deleted. Strategies: `most_recent`, `voting`, `credibility_weighted` (the last reads
a `--credibility source_name.json` map). Bake a resolution into `graph.json` with
`textgraph build ./docs --resolve-conflicts voting`.

**Interoperable exports** — the graph as standard semantic-web artifacts, all deterministic:

```bash
textgraph export ./my-documents --format rdf    -o graph.ttl      # RDF/Turtle triple store
textgraph export ./my-documents --format owl    -o ontology.ttl   # OWL vocabulary
textgraph export ./my-documents --format shacl  -o shapes.ttl     # SHACL shapes
textgraph export ./my-documents --format prov-o -o decisions.jsonld  # PROV-O decision trail
```

The **RDF/Turtle** export loads straight into Oxigraph, Apache Jena, RDF4J, or any SPARQL
store — and cited edges become reified `rdf:Statement`s carrying the re-verifiable byte span,
so provenance survives the round-trip. **PROV-O** renders each decision as a `prov:Activity`
with `CAUSED`/`INFLUENCED`/`PRECEDENT_FOR` as `prov:wasInformedBy`.

Run `textgraph --help` for the full list.

## 7. Running the tests (contributors)

```bash
pip install -r requirements.txt -r requirements-dev.txt   # or: uv sync --extra dev
pytest -q
ruff check . && ruff format --check . && mypy
```

---

Trouble? `textgraph: command not found` usually means the virtual environment isn't
activated (or you skipped `pip install -e .`); with uv, prefix commands with `uv run`.
