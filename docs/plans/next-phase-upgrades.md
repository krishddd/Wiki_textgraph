# Next-phase upgrades — grounded plan

Your upgrade map, checked against the actual codebase. Three things came out of that check:

1. **Some of it already exists.** The REST Ask endpoint ships today; multi-turn memory has a
   working one-slot foundation; `watch` already has the hook the Slack bot needs; the LLM cache
   already counts hits and misses. Those move from "build" to "finish + expose."
2. **Four of your asks are the same missing primitive.** Visual graph diff, entity watchlist,
   Slack alerting, and answer-comparison mode all need *"what changed between graph A and
   graph B."* There is no diff anywhere in the tree today. Build it **once** as a library
   function and all four become thin wrappers.
3. **One item is riskier than it looks** — citation click-through needs source bytes the console
   does not always have. Called out below rather than discovered mid-build.

Guardrails held throughout: `graph.json` stays byte-identical and deterministic (G1); anything
model-authored stays `GENERATED` (G4); analyst annotations never touch the deterministic graph.

---

## Reality check on effort

| Item | Your estimate | Actual | Why |
|---|---|---|---|
| REST endpoint for Ask | Medium | **Already shipped** | `POST /api/chat` (`console/api.py:79`) returns `{tool, text, focus, evidence, highlight:{nodes,edges}, detail, confidence, abstained}`. Needs a documented `/api/ask` alias + session id — not a build. |
| Multi-turn memory | Medium | **Low–Medium** | `answer(..., focus=...)` already threads a one-slot focus, and `_one_entity` (`chat.py:86`) already resolves bare follow-ups against it. This is promoting one slot to a session object, not new plumbing. |
| Slack / Teams bot | Low | **Low — confirmed** | `watch(on_build=Callable[[BuildResult], None])` (`watch.py:37`) is exactly the hook. But it fires on *every* rebuild — without a diff it can only say "something rebuilt," so it depends on the diff primitive. |
| LLM cache status | Low | **Low — confirmed** | `PromptCache` already tracks `.hits` / `.misses` (`cache.py:23-24`). Mostly surfacing. |
| Edge type filter | Low | **Low — confirmed** | Mirrors the existing tag-chip code (`renderer.py:813-815`); add `S.preds` beside `S.tags` and one filter line in `draw()`. |
| Citation click-through | Medium | **Medium — with a caveat** | **Nothing serves source text by byte span today.** Needs a new `/api/source?doc=&start=&end=`. Caveat: the console can run from a `.duckdb` or a bare `graph.json` with **no corpus dir**, so this must degrade gracefully instead of 500ing. |
| Answer comparison mode | High | **Low, if sequenced** | Becomes a thin UI over the diff primitive instead of its own subsystem. Deprioritized until diff lands. |
| Visual graph diff | High | **Medium** | The primitive is a set-difference over content-addressed ids — the hard part (stable ids) is already solved by design. |

---

## The unifying primitive

```
textgraph/l9_artifacts/diff.py

  graph_diff(old_nodes, old_edges, new_nodes, new_edges) -> GraphDiff
      added_nodes / removed_nodes / added_edges / removed_edges
      changed_claims      (confidence or [t_valid,t_invalid) moved)
      new_contradictions  (CONTRADICTS edges not in old)
      community_shift     (entities whose community id changed)
```

Deterministic, pure, no I/O — sorted set operations over content-addressed ids. **This one
function unlocks:** `textgraph diff` CLI · visual diff HTML (green/red) · entity watchlist ·
Slack/Teams alerts · answer comparison. Build it first in the release that needs it.

---

## Release plan

### v4.8.0 — "An investigation conversation" (the Ask dock)

Your highest-ROI pick, and the codebase agrees: the scaffolding is already there.

| # | Change | Notes |
|---|---|---|
| 1 | **Session memory.** Promote the single `focus` slot to a `ChatSession` (last N turns: question, tool, focus, returned node ids). Follow-ups like *"who else is connected to them?"* resolve pronouns against the last turn's entities. Server keeps sessions in memory keyed by a client-generated `session_id`. | Extends `answer()`; `forget()` already exists for rebuild invalidation. |
| 2 | **Suggested next questions.** After each answer, 3 chips derived **deterministically** from the returned nodes/edges (top entity → *"why is X in this case?"*; two entities → *"trace the path"*; community w/ contradictions → *"show contradictions here"*). | Rule-based on purpose — no LLM, so it works in the zero-LLM default. |
| 3 | **Citation click-through.** New `GET /api/source?doc=&start=&end=` returns the span plus surrounding context; clicking a `[doc:123-456]` opens a source panel scrolled to it, highlighted. Re-verifies the span hash on read, so the panel proves the citation. | **Degrades gracefully** to today's text-only citation when the console has no corpus dir. |
| 4 | **Routing inspector.** Collapsible "how this was answered": chosen tool, resolved entities, and — for GQL — the actual query, editable and re-runnable. | Teaches the query language; `classify()` already returns the tool. |
| 5 | **`/api/ask` + documented REST.** Alias with `session_id` support, documented in README so dashboards/Slack/Jupyter can call it. | Thin wrapper over the existing route. |
| 6 | **Export chat as report.** Session → Markdown (questions, answers, citations, tools used) via the existing `GRAPH_REPORT.md` writer. | Low. |

### v4.9.0 — "Reading the map" (visualization)

683 edges on screen is the problem to solve.

| # | Change | Notes |
|---|---|---|
| 1 | **Edge-type filter.** Predicate chips beside the tag chips — toggle `TRANSFERRED` / `CONTROLS` / `CO_OCCURS` / `SAME_AS` independently, with counts. Includes a "hide backbone" one-click to drop `CO_OCCURS` and see only semantic relations. | The single biggest readability win for your current graph, where 670 of 683 edges are `CO_OCCURS`. |
| 2 | **Timeline animation.** Play/pause on the existing time slider, stepping the existing `dates` keyframes; edges fade in/out as claims become valid/invalid. | Data already there (`t_valid`/`t_invalid` per edge). |
| 3 | **Contradiction heatmap.** Tint communities/nodes by `CONTRADICTS` count — contested zones at a glance. | Low; `CONTRADICTS` edges already in the graph. |
| 4 | **Mini-map.** Corner thumbnail with a viewport rectangle, click-to-jump. | Low; reuses the draw loop at a second scale. |
| 5 | **Subgraph export.** Select nodes (community picker or lasso) → export as `graph.json` / SVG / PNG. | Share one fraud cluster without the corpus. |

### v4.10.0 — "What changed" (the diff primitive + what it unlocks)

| # | Change | Notes |
|---|---|---|
| 1 | **`graph_diff()` library function** + `textgraph diff a.json b.json` (text/JSON output). | The primitive. Deterministic set ops. |
| 2 | **`--html` visual diff** — added green, removed red, changed amber, in the existing viewer. | Audit trail for AML case builds. |
| 3 | **Entity watchlist** — `watchlist.json` of priority entities; on each `watch` rebuild, diff their claims and report new relations / confidence changes / new contradictions. | Pure diff consumer. |
| 4 | **Webhook alerts** — `textgraph watch --webhook <url>` posts a JSON summary of the diff (Slack/Teams-compatible) through the existing `on_build` hook. Opt-in, off by default; the only feature here that touches the network. | ~30 lines *because* the diff exists. |
| 5 | **Answer comparison** — ask one question against two builds, diff the answers side by side. | Now a thin UI, not a subsystem. |

### v4.11.0 — "Closing the analyst loop"

| # | Change | Notes |
|---|---|---|
| 1 | **Contradiction resolution hints.** For each `CONTRADICTS`, compute a deterministic recommendation ("Claim A is newer *and* higher-confidence — B is likely superseded") with a one-click **invalidate** that writes a cited `SUPERSEDES` edge. | Detection + `resolve_conflicts` already exist; this is the analyst-facing loop, and it stays non-destructive. |
| 2 | **Annotation layer.** Analyst notes / statuses (`confirmed` / `disputed` / `pending`) in a sidecar `annotations.json`, shown as a marker on canvas. **`graph.json` is never touched**, so determinism holds. | The sidecar design is what makes collaborative mode possible later. |
| 3 | **Streaming build progress.** SSE from the local server; L0→L9 progress in the console during `watch`. | Removes the black box. |
| 4 | **LLM cache panel.** `textgraph cache status` + console panel: hit rate, calls saved, uncached chunks — warm the cache before a meeting. | `PromptCache.hits/misses` already counted. |

### Later — bigger bets (each its own release)

- **Node2Vec structural embeddings** — "find entities playing the same structural role as Acme
  Corp." Genuinely high effort and the first thing here that adds a heavy dependency; it is also
  the highest-value one for shell-company pattern detection. Wants its own design doc.
- **Semantic entity search** — `[embed]` + `dense.py` already exist, so this is Medium: an
  entity-level index beside the chunk-level one.
- **Cross-graph federation** — query two `graph.json` files at once for cross-case linking. Needs
  an id-namespacing design (the same entity key in two corpora is not automatically the same
  entity) — that design question, not the code, is the hard part.
- **Jupyter integration** — `graph.show()` inline + citation-bearing DataFrames. Medium, self-contained.
- **Collaborative mode** — only sensible after the annotation sidecar (v4.11) proves the shape.
- **More vector backends (Qdrant/FAISS)** — deferred: real value only once a corpus outgrows the
  in-memory index, which yours does not.

---

## Recommended order

Your instinct — *Ask memory → edge filter → resolution hints → Slack* — is right on ROI. One
change: **the edge-type filter should ship first.** It is a few hours of work, and on your
current graph (670 of 683 edges are `CO_OCCURS`) it is the difference between a hairball and a
readable map. Then:

**Edge-type filter → v4.8.0 Ask dock → v4.9.0 rest of visualization → v4.10.0 diff + Slack →
v4.11.0 analyst loop.**

Resolution hints land in v4.11 rather than earlier because the one-click invalidate is most
convincing once the diff can *show* what the invalidation changed.

## What I'd skip for now

- **More vector store backends** — no corpus pressure yet; cost without benefit.
- **Answer comparison as its own feature** — free once diff exists; expensive before.
- **Collaborative investigation mode** — needs a shared-state server, which contradicts
  local-first until there is a second user asking for it.
