# Plan — "Ask" chat panel for the TextGraph console

**Status:** Phase 0 + A + B **shipped** (grounded chat dock, deterministic, no LLM).
Remaining: C (file-attach ingestion), D (opt-in LLM narration + options), E (polish).
See §8; the review that reordered the phases (engine-injection prerequisite, multi-turn,
POST) was applied before implementation.
**Goal:** add an Antigravity-style chat dock to the bottom of `textgraph console`. The user
types a question (and can attach files); the assistant answers in the chat **and** drives
the graph beside it — highlighting the nodes and paths the answer is about — with every
claim cited back to source bytes. It stays true to TextGraph's rules: deterministic and
local-first by default, the LLM strictly opt-in, `graph.json` untouched.

---

## 1. What "like Antigravity" means here

Google Antigravity (agent-first IDE, Nov 2025) is the UX reference the user pointed at. The
patterns worth borrowing, mapped to TextGraph:

| Antigravity pattern | TextGraph adaptation |
|---|---|
| Chat/agent panel as the primary surface | A bottom **chat dock** in the console, graph stays visible beside it |
| Tools/skills loaded on demand, not all at once | Question is **routed** to one of the graph tools (reason/search/path/gql/why/…) |
| File/project context you attach | **Attach files** → ingest into the graph (incremental), answer over the new content |
| Verifiable **Artifacts** (plans, results you can inspect) | The **Graph-of-Thoughts chain** + **citations** are the artifact — every step clickable to the graph |
| Options / model choice | A small **toolbar**: tool mode, reasoning depth, grounded-vs-narrated answer |

The one thing we deliberately do **not** copy: an autonomous agent that edits your machine.
This assistant is read-mostly and evidence-bound; the only write action is opt-in file
ingestion, gated (see §5).

## 2. Core idea — a grounded answer that moves the graph

Every answer is produced by the **existing** query surface, never invented:

```
question ──► intent router ──► graph tool(s) ──► ChatAnswer{ text, evidence[], highlight{nodes,edges}, trace }
                (deterministic)   reason()/search()/path()/gql()/why()/…        │
                                                                                 └─► frontend highlights the graph
```

`ChatAnswer.highlight` carries node ids + path edges, which the renderer already knows how
to emphasize (`S.match`, `S.pathEdges`, `inspect()`), so the graph reacts to the
conversation. `evidence` is the list of `[doc:start-end]` citations, rendered inline and
clickable. `trace` is the Graph-of-Thoughts thought-chain for "how/why/connect" questions —
the inspectable "artifact."

### Two answer modes (the LLM stays optional — G2)

- **Grounded (default, no LLM, deterministic).** The router classifies the question and
  calls the matching tool; the answer text is a **template** filled from the cited result.
  Zero network, zero GPU, fully reproducible. This is the whole feature working end-to-end
  with nothing installed.
- **Narrated (opt-in).** If an LLM key is present (existing `resolve_client(config)` returns
  a client instead of `None`), the same grounded evidence is handed to the LLM to phrase a
  fluent answer — **`GENERATED`-tagged, citations preserved, facts never fabricated** (the
  ESCARGOT pattern already used by the reasoner). The graph tools remain the source of
  truth; the LLM only rewords.

## 3. Intent routing (deterministic, no LLM)

A small, testable classifier maps a question to a tool. Rule-first, cheap, deterministic:

| Question shape (cues) | Tool | Highlight |
|---|---|---|
| "how is X connected to Y", "link between X and Y", "path from X to Y" | `path` + `reason` | the path's nodes+edges |
| "why", "what do we know about X", "explain X" | `why` | X + its claim neighbours |
| "who/what/which … " (entity lookup), free text | `search` | matched entities |
| "neighbours of X", "what is X related to" | `neighbors` | X + neighbours |
| "when did X change", "timeline of X" | `timeline` | X |
| "contradictions", "conflicts" | `contradictions` | the conflicting claim pairs |
| "communities", "clusters", "overview" | `communities` / `stats` | community colours |
| starts with `MATCH`/`RETURN` | `gql` | returned nodes |
| "reason:", complex multi-entity questions | `reason` (Graph-of-Thoughts) | the reasoning chain's spans |

Entities are resolved with the engine's existing `resolve()` / `search()`. Unroutable
questions fall back to `reason()` (which itself falls back to the top search hit — the
Phase-10 review fix), so the user always gets a grounded answer or an honest "no evidence."

## 4. Backend design (pure, testable, no new deps)

Mirror the existing console split (`api.py` pure `route()` + `server.py` socket shell):

- **`textgraph/console/chat.py`** — `answer(engine, question, opts) -> ChatAnswer`. Pure
  function: intent-route → `call_tool` / `reason()` → assemble `ChatAnswer`. Unit-tested
  with no socket, exactly like `test_console.py`. Optional narration via
  `resolve_client(config)` (skipped when `None`).
- **Extend `call_tool`** (mcp/tools.py) with `reason` and `gql` so the chat and the MCP
  server share one dispatcher (G6 — one surface, many formatters).
- **New routes** in `api.py`:
  - `GET /api/chat?q=…&mode=…&tool=…` → `ChatAnswer` JSON.
  - `POST /api/ingest` (multipart) → incremental ingest, returns what was added (§5).
    Requires adding `do_POST` to the handler in `server.py` (http.server, still stdlib).
- **`ChatAnswer`** dataclass in `console/model.py` (or reuse `l8_retrieval/model` style):
  `{ text, tool, mode, evidence:[Citation], highlight:{nodes:[id], edges:[[s,t]]}, trace? }`.

Everything read-only stays read-only; the reasoner and tools are already deterministic.

## 5. File attach → incremental ingestion (the only write path)

Dropping files into the chat ingests them into the live graph:

1. `POST /api/ingest` saves the upload to the corpus dir (or a temp overlay).
2. Runs the **existing incremental pipeline** (`core/incremental.py` per-doc cache keyed by
   `(doc_id, config_hash)`) — only the new/changed docs are extracted; result is
   byte-identical to a full rebuild (already guaranteed and tested).
3. Rebuilds the in-memory `QueryEngine`, re-serves `/api/graph`; the frontend diffs and
   **animates in the new nodes**.
4. The chat posts a grounded confirmation: "Added `contract.pdf` → 3 entities, 2 relations
   (cited)."

**Guardrails (important):**
- Ingestion is a **mutation**, so it is **off unless `--allow-ingest` is passed** to
  `textgraph console`, and only ever writes inside the corpus dir. Default console stays
  read-only.
- Bind stays localhost by default; document the risk before `--host 0.0.0.0`.
- File-type validation reuses the L0 ingester's format guard; oversize/refused files are
  reported in chat, not silently dropped.
- If the corpus has a Phase-9 policy attached, ingestion and answers honour the caller's
  `SecurityContext` (future: a principal picker in the toolbar).

## 6. Frontend design (self-contained, no CDN — extends renderer.py)

- **Layout:** the graph card shrinks; a **chat dock** occupies the bottom of the main
  column (collapsible). Messages list (user / assistant bubbles) + an input row with:
  attach (📎), a **tool chip** (`auto ▾` → reason/search/path/gql/why/…), a depth toggle
  (adaptive/static for reason), and send. Slash-commands (`/path A B`, `/gql …`, `/reason
  …`) map to tools directly.
- **Answer rendering:** assistant bubble shows the templated/narrated text, an **evidence
  list** of clickable `[doc:span]` chips (click → inspect that node), and, for `reason`,
  an expandable **thought-chain** (Plan → SubProblem → Hypothesis → Verification →
  Summary) — the verifiable artifact.
- **Graph coupling:** on each answer, call the existing highlight paths — set `S.match`
  from `highlight.nodes`, `S.pathEdges` from `highlight.edges`, `fitTo()` the focus, and
  `draw()`. Hovering an evidence chip flashes its node.
- **Adapter:** add `TG.chat(q, opts)` and `TG.ingest(files)` to the live adapter
  (`page.py`). The **offline `graph.html` has no server**, so it gets a static "chat needs
  the live console" note — the shared renderer degrades gracefully (chat dock hidden when
  `TG.chat` is absent), so the two surfaces still don't fork.

## 7. Determinism, security, and the sacred rules

- **G1 determinism:** the chat is query-time and read-only over the assembled graph;
  `graph.json` is byte-identical. The grounded router is deterministic. Narrated mode is
  opt-in and `GENERATED`-tagged, exactly like the existing L4 pass, so the determinism gate
  never sees an LLM.
- **G2 local-first:** default install answers fully offline; no CDN, no framework, stdlib
  `http.server` only.
- **G3 provenance:** every factual line carries a re-verifiable citation; narrated text may
  not introduce a claim without one.
- **Phase-9 FGAC:** answers route through the same engine, so an attached policy +
  principal is honoured; ingestion respects it too.

## 8. Phased delivery (each phase ships green, tests + determinism intact)

| Phase | Deliverable | Tests |
|---|---|---|
| **A** | `console/chat.py` `answer()` + intent router + `/api/chat`; `call_tool` gains `reason`/`gql`. Grounded, cited, no UI. | pure-function unit tests (no socket), determinism unaffected |
| **B** | Chat dock UI + graph-highlight wiring (grounded only). | renderer/page smoke; console API tests extended |
| **C** | File attach + `/api/ingest` (incremental) behind `--allow-ingest`; live node-add animation. | ingest round-trip = byte-identical; guard tests |
| **D** | Opt-in **narrated** mode via `resolve_client`; tool/depth/model options; slash-commands. | mock-client tests (like the L4 suite) |
| **E** | Polish: message history, evidence hover-to-flash, thought-chain artifact panel, export chat. | UI smoke |

Recommend shipping **A + B** first (the whole grounded experience) and treating C/D/E as
follow-ons.

## 9. Open decisions (need your call)

1. **Ingestion in v1?** Include file-attach now (Phase C, adds a write path + `do_POST`), or
   ship the grounded chat first and add ingestion after?
2. **Narrated mode default?** Keep the LLM strictly opt-in (recommended, preserves G2), and
   only turn on when a key is set — confirm.
3. **Scope of "extra tools":** expose all 8 tools + `reason` + `gql` as chips/slash-commands,
   or a curated few (search / path / reason / why)?
4. **Where the chat lives:** bottom dock (recommended, graph stays beside it) vs a right-side
   panel vs a toggle that swaps the inspector.

---

### Effort estimate

- Phase A+B (the core grounded chat that moves the graph): ~1 focused unit.
- Phase C (ingestion): ~0.5 unit. Phase D (narration + options): ~0.5 unit. Phase E: ~0.5.

### Files touched (A+B)

`textgraph/console/chat.py` (new), `textgraph/console/api.py`, `textgraph/mcp/tools.py`,
`textgraph/console/renderer.py`, `textgraph/console/page.py`, `tests/unit/test_console.py`
(+ a new `test_chat.py`). No new dependencies.
