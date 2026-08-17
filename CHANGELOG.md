# Changelog

All notable changes to TextGraph are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to Semantic Versioning.

## [Unreleased]

## [4.11.0] - 2026-08-17

### Added — the diff primitive (what changed between two builds)
- **`graph_diff()`** (`textgraph/l9_artifacts/diff.py`): a deterministic, read-only set-difference
  between two builds — added/removed entities and relations, changed relations (confidence, tag,
  evidence) and claims (validity window, polarity), new/resolved contradictions, and community
  membership moves. Reliable because ids are content-addressed, so the same fact keeps the same
  id across builds; **community ids (renumbered per build) are diffed by membership, never by id.**
- **`textgraph diff A B`** — CLI over the primitive. Each side may be a `graph.json`, a directory
  containing one, a `.duckdb` store, or a corpus (built on the fly). `--json` for pipelines,
  `--entities NAMES` to restrict the diff to a watchlist.
- **`textgraph watch --webhook URL`** — the one opt-in network feature: on each rebuild after the
  first, diff the previous and current graphs and POST a Slack/Teams-compatible summary. Failures
  are logged, never fatal (`textgraph/alerts.py`). **`--watchlist FILE`** restricts alerts to a
  named set of entities. A new `on_diff` hook on `watch()` powers both.

### Added — the analyst loop
- **Contradiction resolution hints** (`textgraph/l6_graph_model/resolution.py`,
  `QueryEngine.resolution_hints()`): for each `CONTRADICTS` pair, a deterministic recommendation of
  which claim likely supersedes — by **recency** (a dated correction wins) then **confidence** —
  with a rationale. **Read-only and non-destructive**; the console's contradictions view now shows
  a "recommends A/B" badge and the reason. Applying it stays an explicit, cited `SUPERSEDES` step.
- **Analyst annotation sidecar** (`textgraph/console/annotations.py`): mark an entity
  `confirmed` / `disputed` / `pending` and attach a note, from the node inspector. Stored in a
  separate `annotations.json` (`console --annotations FILE`) — **`graph.json` is never touched and
  stays byte-identical (G1).** Annotated nodes carry a coloured marker on the canvas. The seed of
  collaborative review: immutable shared graph, mutable overlay.
- **`textgraph cache status PATH`**: report how warm the LLM prompt cache is (entries, size) so an
  analyst can tell before a meeting whether an `--llm` rebuild will be free or spend calls. Only
  real cache entries are counted, so a build-output dir's `graph.json` is never mistaken for a
  warm cache.

All of this is deterministic and read-only except the annotation sidecar, which only ever writes
its own file. `graph.json` and the determinism gate are untouched.

## [4.10.0] - 2026-08-17

### Added — reading the map (graph visualization)
- **Timeline animation.** A play/pause button on the time slider steps through the claim
  keyframes so edges appear and disappear as claims become valid/invalid — the bi-temporal data
  animated instead of scrubbed by hand. Deterministic keyframe order; scrubbing by hand pauses
  playback; it stops at the final keyframe.
- **Contradiction heatmap.** A **Heat** toolbar toggle tints each entity by how many contested
  (`CONTRADICTS`) claims it carries — deep red for the most-contested, neutral grey for the rest —
  so an investigator sees the contested zones at a glance instead of reading the report. Backed
  by a new per-entity `contradictions` count in the `/api/graph` payload (a `CONTRADICTS` edge is
  attributed back to the entity each contested claim is *about*). One colour encoding at a time:
  turning on Heat turns off Ego and vice-versa.
- **Mini-map.** A corner overview (shown once a graph exceeds ~12 nodes) draws the whole graph at
  a glance with a viewport rectangle; click or drag it to recentre the main view. Heatmap-aware,
  so contested zones show in the overview too.

All three are client-side and ship in the offline `graph.html` as well; `graph.json` is
untouched and determinism is unaffected. The only backend change is the additive
`contradictions` field on graph-view nodes.

## [4.9.0] - 2026-08-17

### Added — the Ask dock becomes an investigation conversation
- **Multi-turn memory.** The Ask dock now keeps a bounded, per-tab conversation history on the
  server. A follow-up that leans on the previous turn — *"who else is connected to **them**?"* —
  resolves the pronoun against the last entity in focus and answers about it, instead of
  abstaining for lack of a subject. Resolution is **rule-based and deterministic** (no LLM), so
  it works in the zero-LLM default. A rebuild (in-UI ingest/remove) clears the memory, since node
  ids may change. New `textgraph.console.session` module (`ChatSession`, `SessionStore`,
  `resolve_followup`).
- **Citation click-through.** Clicking a `[doc:start-end]` citation opens a source panel showing
  the exact cited bytes in context, with the surrounding text dimmed and the span highlighted.
  The bytes are **re-hashed against the source on read** and shown as *verified* — a since-edited
  file is reported as a mismatch, never silently shown. New `GET /api/source` +
  `textgraph.console.source`. **Degrades gracefully**: a console with no corpus dir (a bare
  `graph.json` / `.duckdb`), or the offline `graph.html`, keeps the old inert text citation.
- **Suggested follow-ups.** After each answer, up to three chip-style next questions derived
  **deterministically from the returned nodes/edges** (expand the focus, connect two entities the
  answer surfaced, pivot to why/timeline/contradictions). Clicking one asks it. New
  `textgraph.console.suggest`.
- **Routing inspector.** A collapsible "how this was answered" line under each answer: the tool
  chosen, the resolved focus, and — when a follow-up was rewritten — the question actually run.
- **`POST /api/ask`** documented alias for `/api/chat`, accepting a `session_id`, so external
  callers (dashboards, bots, notebooks) get the same multi-turn, cited answers.

## [4.8.0] - 2026-08-15

### Added
- **Relation-type filter in the graph console.** A **Relation types** panel lists every
  predicate in the view as a chip with its edge count (most frequent first) — click to show or
  hide that relation type. Two shortcuts: **All**, and **Semantic only**, which hides the dense
  `CO_OCCURS` backbone and leaves just the meaning relations (`TRANSFERRED`, `DIRECTOR_OF`, …);
  pressing it again restores, so the button is its own undo. Previously the graph could only be
  filtered by confidence tag (`STRUCTURAL`/`EXTRACTED`/`INFERRED`/`GENERATED`), which cannot
  separate a co-occurrence scaffold from a stated relation — both are `STRUCTURAL`.
- The filter is **view-only** and never touches `graph.json`. It ships in the offline
  `graph.html` artifact too, since both surfaces share the renderer. Deselected relation types
  survive a rebuild, so a `watch` reload no longer silently undoes an analyst's filtering.

### Changed
- Drawing, degree, neighbours and ego-distance now all route through one `edgeShown()` test
  (confidence tag **and** relation type), so the filters can never disagree with each other:
  hiding the backbone re-derives degree, which correctly re-reveals which nodes are held up by
  *semantic* relations alone (on the bundled case corpus: 293 connected → 21, and the footer
  reports `13 of 683 relations shown`). Node radius, top-N labelling and the unconnected-fade
  count follow the same recomputation.

## [4.7.1] - 2026-08-15

### Documentation
- **Documented the real backend workflow and how the LLM is actually used.** The README's
  architecture diagram was corrected to show the LLM at its two true opt-in touchpoints —
  relation extraction (`--llm-extract`, an *input* enricher that now runs **before** entity
  resolution/analytics) and synthesis (`--llm`, an *output* pass) — instead of the old,
  misleading "L4 between L3 and L5" placement. Added a **"How a build actually runs"** section:
  the full 11-step pipeline order with per-step confidence tags, and a step-by-step (with
  sequence diagram) of the LLM relation-extraction path — chunk → prompt/cache → JSON triples →
  merge-by-construction onto existing entities → `GENERATED` edges cited to the chunk span →
  flow through L5/L7/L8 — plus the quarantine guarantee and how to run it. The GitHub Pages
  landing page gained a matching "How a build runs" section and an LLM-usage card. Docs only;
  no code or artifact change.

## [4.7.0] - 2026-08-15

### Fixed
- **The "floating dots" bug — LLM-extracted entities are now first-class.** LLM relation
  extraction ran *after* entity resolution, analytics, and layout, so every entity it
  contributed left the pipeline unranked (`pagerank == 0`), unclustered (`community == -1`),
  and unplaced (`x == y == 0`) — a field of dots at the origin with long chords crossing the
  canvas. Extraction now runs **before** L5/L7, so those entities flow through resolution,
  PageRank, community detection and force-layout like any other node. On a 470-entity case
  graph this was 153 entities (32%) sitting at the origin. A build invariant now asserts no
  entity leaves L7 without a position and a real community, so the bug cannot silently return.
- **No more duplicate `entity:LLM:` dots.** A triple endpoint whose name matches an entity the
  deterministic pipeline already produced now **reuses that node's id** (merge-by-construction)
  instead of spawning a parallel node that split a single thing's relations across two dots.
  Near-misses are still fuzzy-linked by L5 entity resolution.
- **`LLM` is no longer shown as an entity type.** It was a provenance stamp (`etype: "LLM"`)
  leaking into the type legend; provenance stays on `source: "llm"` + the `GENERATED` edge tag,
  and merged nodes inherit their real type.

### Added
- **Co-occurrence backbone (`textgraph build --co-occurrence`).** For a corpus that names many
  entities but states few explicit relations, this adds `STRUCTURAL` `CO_OCCURS` edges between
  entities co-mentioned in the same chunk — cited by the shared chunk's byte span — so
  analytics, communities and layout see a **connected, clustered** graph instead of a dust of
  orphans. Deterministic and opt-in (the baseline determinism gate is untouched). New
  `textgraph/l6_graph_model/cooccurrence.py`. Distinct from the console's view-only fallback:
  these are real graph edges the analytics actually run on.
- **Graph console: focus mode + readability.** Unconnected nodes fade to the background by
  default (toggle with the ◉ rail button or **F**), with a live "N unconnected" count in the
  status line, so structure is what you see first. The top-25 PageRank nodes are always
  labelled (no zoom needed); node radius now also reflects degree; over-long "passing" edges
  fade; and the community roster collapses hundreds of singleton clusters into one "N isolated
  entities" row.
- **Graph-health panel in `GRAPH_REPORT.md`.** Orphan %, singleton-community %, duplicate-name
  candidates, and an unlaid/unranked bug tripwire — the exact signals from the quality audit,
  with a one-line hint to enable `--co-occurrence` / `[er]` when the graph is thin.

## [4.6.0] - 2026-08-14

### Added
- **openCypher export → Neo4j / Memgraph / AGE / Neptune.** `textgraph export --format cypher`
  emits a deterministic, idempotent load script (`MERGE` nodes on `id`, `MATCH … MERGE` the
  relationships) that recreates the whole graph in any Bolt / openCypher database. Every
  relationship keeps its `ConfidenceTag`, confidence, original predicate, and `[doc:start-end]`
  byte citation as properties, so provenance re-verification (G3) works over the graph store
  too. Pure string emission — no driver dependency; the DB is a downstream **materialization
  target** for the already-built `graph.json` (per `docs/plans/neo4j-backend.md`), so the build
  stays local and deterministic. Relationship types and labels are sanitised to valid Cypher
  identifiers; string values are escaped; output is byte-stable (G1). New
  `textgraph/l9_artifacts/cypher.py::export_cypher_bytes`.

## [4.5.0] - 2026-08-14

### Added
- **Smoother graph interaction.** Clicking a node now glides the camera to it (eased) and
  draws a soft selection halo; clicking the **same** node again, clicking empty canvas, or
  pressing **Escape** clears the selection ("undo"). Faded (non-neighbour) nodes are clickable
  again, so you can jump straight from one focus to another. Dragging or zooming cancels an
  in-flight glide so manual control always wins.

### Fixed
- **Top search box now actually shows results.** A query matching entities highlighted them
  off-screen (and a no-match query faded the *entire* graph to near-invisible, so it looked
  broken). Search now pans/zooms the camera to the matches, and on no match keeps the whole
  graph visible with a clear message (plus any passage hits) instead of blacking it out.
- **Grouped view is readable.** Instead of drawing hundreds of overlapping community hulls and
  labels, **Group** now lays each community out as its own separated circular cluster on a
  grid, and labels only the largest clusters. Toggling Group off restores the previous layout.

## [4.4.1] - 2026-08-14

### Changed
- **Positioning refresh.** The one-line description (PyPI summary, README tagline, package
  docstring, and docs landing) now reflects what TextGraph grew into this cycle: an
  **interactive graph studio**, **link prediction**, and **Datalog rule reasoning**, on top of
  the deterministic/local-first/byte-cited core (with opt-in LLM extraction and semantic
  search). PyPI is immutable, so the summary only refreshes on a new version — hence this
  docs-only patch.

## [4.4.0] - 2026-08-14

### Changed
- **Studio-style console chrome** (Semantica-inspired). The console now has a slim **left rail**
  (brand + quick shortcuts: fit, ego, group, full-width, theme) spanning the full height, a
  **segmented top toolbar** with labelled *Analyze* (Ego / Path / Group) and *View* (Fit /
  full-width) bands, and **collapsible inspector sections** — click any right-panel header
  (Communities, Top entities, Confidence tags, Documents) to fold it. Rail shortcuts stay in
  sync with the header toggles. Verified in-browser: full height/vertical fit preserved, no
  horizontal scroll, no console errors. The offline `graph.html` artifact inherits the same
  chrome. Layout/chrome only — no change to the graph engine or `graph.json`.

## [4.3.0] - 2026-08-14

### Added
- **Forward-chaining rule engine (Datalog subset)** — the biggest remaining Semantica
  capability gap (their reasoning module). `textgraph/reasoning/` derives new relations from
  existing ones with recursive IF/THEN rules (`FUNDS_REACH(X, Z) :- TRANSFERRED(X, Y),
  TRANSFERRED(Y, Z).`), joined to a fixpoint. Cycle-safe (finite, monotonic fact set),
  deterministic, and **fully explainable** — every derived fact keeps the rule that fired and
  the exact body facts that supported it. Surfaced three ways:
  - `QueryEngine.apply_rules(rules_text)`
  - `textgraph rules <path> "<rules-or-file>"` CLI verb
  - a **Rules (Datalog)** tool in the console Ask dock — type a rule, derived facts light up
    as edges with their derivation listed. (Uppercase terms are variables; lowercase/quoted
    are constants.)
  Derived facts are inferences surfaced at query time, never written into `graph.json`
  (determinism/provenance gates untouched).

## [4.2.0] - 2026-08-14

### Added
- **Ego / distance-intelligence view in the console.** An **Ego** toggle in the toolbar turns
  the graph into a distance map: click any node to make it the focus, and every other node is
  coloured by how many hops it sits from it — 0h (focus), 1h, 2–3h, 4+h — with nodes beyond
  the chosen depth faded out. A depth slider (1–6 hops) re-roots the neighbourhood live, and a
  banner reports the focus and how many nodes fall within range (e.g. *"focus MTOR · 218
  within 3 hops"*). Pairs naturally with link prediction for exploring a node's structural
  reach. Pure client-side (BFS over the shown relation graph); `graph.json` untouched.

## [4.1.0] - 2026-08-14

### Added
- **Structural link prediction** — a new deterministic capability that suggests likely-missing
  relations from graph topology, matching the one substantial Semantica KG-engine feature
  TextGraph lacked. `textgraph/l7_analytics/link_prediction.py` scores unconnected entity
  pairs by shared-neighbour overlap (**Adamic-Adar** default, plus common-neighbours and
  resource-allocation), returning the top candidates with the shared entities that drove each
  one (explainable, byte-reproducible). Surfaced three ways:
  - `QueryEngine.predict_links(handle=None, index=..., k=...)`
  - `textgraph predict <path> [node] [--index] [-k]` CLI verb
  - a **Predict links** tool in the console Ask dock — predictions render as **dashed
    candidate edges** on the graph, with the shared-neighbour evidence listed in the reply.
  Predictions are suggestions from structure, so they carry no citations and are never written
  into `graph.json` (query-time only; determinism/provenance gates untouched).

## [4.0.1] - 2026-08-14

### Changed
- **Tighter console chrome, more room for the graph.** The four stat cards are now a slim
  single-line strip (~42px tall instead of ~90px), so the graph canvas gets the reclaimed
  height. The side inspector is a flex column that always fits the page: the community
  roster, top-entities list, and document list each cap out and **scroll inside their own
  section** (verified: nothing overflows the viewport, no page scroll), and the selected-node
  detail takes whatever height is left and scrolls internally. Sidebar rows are a touch
  shorter. No functional change — layout only.

## [4.0.0] - 2026-08-14

The **NotebookLM-style graph console** release. The web viewer went from a static
force-laid dashboard to a self-organising, meaning-rich mind-map, and opt-in LLM relations
are now first-class citizens on the canvas. `graph.json` and every gate are untouched — all
of this is console-view behaviour.

### Added
- **LLM-extracted relations are always visible.** `--llm-extract` creates `entity:LLM:` nodes
  that carry little PageRank, so their `X →REGULATES→ Y` edges used to fall below the top-N
  rank cutoff and never render. The graph view now keeps every explicit-relation endpoint
  first (LLM and rule relations alike), then fills the remaining budget by PageRank — so the
  meaningful relations you built always show. On a sample corpus this took the shown relation
  count from **1 to 239**.
- **NotebookLM / Semantica-style mind-map layout** (from 3.8.0–3.9.1, consolidated here): a
  client-side force layout clusters connected entities and fills the panel; a co-occurrence
  backbone links entities that share a passage (hub-and-spoke for large passages) so a
  relation-sparse build still spreads instead of collapsing to a ring; unlinked nodes scatter
  as a filled halo. A ↔ toggle collapses the side panel for full-width graph.
- **`build --llm-extract-budget N`** to dial LLM relation-extraction density (default 40).

### Changed
- Communities panel capped to the top 40 clusters (`+ N smaller clusters`).
- README + Status describe the mind-map console and the always-visible LLM relations.

### Fixed
- Canvas re-fits after the Ask dock collapses/expands and after the full-width toggle.

## [3.9.1] - 2026-08-14

### Changed
- **The map now fills the canvas instead of forming a circle.** The co-occurrence backbone
  links far more entities — larger passages are connected hub-and-spoke to their strongest
  member (instead of being skipped), so on a typical corpus ~87% of shown nodes are connected
  (was a large unlinked ring). The few genuinely unlinked nodes now scatter as a filled halo
  disc (a Vogel spiral), never a hard ring, so the graph spreads across the whole panel.

### Fixed
- **Collapsing the Ask dock no longer leaves the graph mis-sized.** The canvas buffer is now
  re-fit after the dock expands/collapses (and after the full-width panel toggle).

### Added
- **Co-occurrence backbone so the graph spreads across the panel.** When a build has almost
  no explicit relations (deterministic extraction of prose that names entities but states few
  hard relations), the console now links entities that are mentioned together in the same
  passage — a `CO_OCCURS` edge tagged `STRUCTURAL`. The map spreads like a proper
  Semantica/NotebookLM graph instead of collapsing to a ring of unconnected dots. The fallback
  is automatically suppressed once real relations exist, so an LLM-extracted graph keeps its
  own semantic predicates. Console view only — `graph.json` and the determinism/provenance
  gates are untouched.
- **Full-width graph toggle (&#8596;).** A header button collapses the side inspector so the
  graph fills the entire panel, then refits automatically.

## [3.8.0] - 2026-08-14

### Added
- **NotebookLM-style mindmap layout in the console.** The graph viewer now runs a client-side
  force-directed layout (Fruchterman-Reingold) on load: connected entities pull together into a
  radial map and unlinked entities are parked on an outer ring, instead of relying on the
  server's scattered positions. Once a build has relations, the console reads as a linked
  mind-map rather than dots in lines. Relation edges are also drawn more prominently.
- **`build --llm-extract-budget N`** — raises the number of chunks the LLM relation extractor
  reads (default 40). Crank it up (e.g. `200`) for a denser, NotebookLM-style relation tree on
  larger corpora. Calls are still prompt-cached, so re-runs are free.

### Changed
- **De-cluttered the Communities panel.** On corpora with hundreds of clusters the sidebar
  rendered every one; it now shows the top 40 by size with a "+ N smaller clusters" line.

## [3.7.1] - 2026-08-08

### Fixed
- **Console layout now fits the browser tab; the Ask dock is always visible.** `#main` (a grid
  child) was missing `min-height:0`, so on shorter viewports its flex children overflowed and —
  with `overflow:hidden` — the **Ask** chat dock was clipped off the bottom (you couldn't ask
  questions). The graph canvas now shrinks to fit and the Ask box stays on-screen, no page
  scroll. (`min-height:0` on `#main`, `#ask` is `flex:none`.)

## [3.7.0] - 2026-08-08

### Changed
- **Nodes are coloured by entity type, not community.** The graph previously cycled a palette
  across dozens of communities (colours looked random). Now each node's colour comes from a
  small fixed **type** legend — Organization / Person / Location / Money / Date / Work / Term /
  LLM / Other — drawn top-left over the canvas with per-type counts, the Semantica-style
  category colouring. Community structure is still available via the **Group** overlay and the
  communities panel.

## [3.6.0] - 2026-08-08

### Added
- **Document management in the console** — a **Documents** panel (sidebar) lists the corpus
  files, and with `--allow-ingest` each has a 🗑 **remove** button that deletes the file and
  rebuilds the graph. Pairs with the existing 📎 **upload** (attach) button, so the full
  add / list / remove lifecycle is in the browser — only launching is a terminal command.
  New `GET /api/docs` (list) and `POST /api/remove` (delete + rebuild, gated on
  `--allow-ingest`); `console.ingest.list_documents()` / `remove_document()` (traversal-safe,
  refuses paths outside the corpus and missing files).

## [3.5.0] - 2026-08-08

**Console intelligence + explorability.** The web console gets the "explore + ask" loop and
cleaner retrieval — one terminal command to launch, everything else in the browser.

### Added
- **Click-to-expand neighbours** — clicking a node lights up its neighbourhood (connected
  nodes + edges), so you can walk the graph instead of staring at dots.
- **Relation labels on edges** — predicates are drawn on highlighted edges (and on every edge
  when zoomed in), so the graph reads as *who → how → whom*, not anonymous lines.
- **Grouped view** — a **Group** toggle outlines each community with its label (Semantica-style
  cluster grouping) for large graphs.
- **LLM answers in the Ask dock** — a **Narrate (LLM)** tool composes a grounded, cited answer
  over the retrieved evidence, in the browser (opt-in; needs an LLM endpoint in the env;
  `GENERATED`-quarantined; degrades to a clear message when no endpoint is set).

### Changed
- **Cleaner search** — repeated file-header templates (identical `====` banners across many
  docs) are detected and down-ranked, and result snippets skip the banner/label lines so you
  see real content, not separators. Query-time only; `graph.json` is unaffected.

## [3.4.0] - 2026-08-08

### Added
- **The console can serve a pre-built `graph.json`.** `textgraph console textgraph-out`
  (or `…/graph.json`, or a `.duckdb`) now serves the **already-built** graph instead of
  silently rebuilding with the deterministic default. This means an **LLM-enriched build**
  (`build --llm-extract`) shows *all* its `GENERATED` relations in the UI — previously the
  console rebuilt without the LLM, so a legal/technical corpus (0 deterministic relations)
  looked like disconnected dots. New `load_graph_json()` reconstructs `(nodes, edges)` from
  a written `graph.json` (tags + byte-span citations preserved).

  Typical flow — one build with intelligence, then explore it in the browser:
  ```
  textgraph build ./docs --llm-extract -o out
  textgraph console out
  ```

## [3.3.2] - 2026-08-08

**Prove & guard the investigator defaults.** PDF ingestion and entity resolution have run
by default since 3.0 — this release makes that *visible and regression-proof*, per the
"do users know it does?" gap in the market review.

### Added
- **`benchmarks/defaults.py`** — a zero-config-defaults benchmark: proves a *default* install
  (no flags, no extras) ingests PDFs (`pypdf` core) and resolves entity aliases (rules ER),
  with a **before/after** table (Acme surface forms unified under one canonical via `SAME_AS`)
  and build/query latency. Written into [BENCHMARKS.md](BENCHMARKS.md).
- **Regression guard** (`tests/unit/test_defaults.py`) — locks in: PDF ingests on the default
  install, `pypdf` stays a *core* dependency (not the `[ingest]` extra), entity resolution is
  on by default (`resolve_entities=True`, `er_backend="rules"`), and a default build resolves
  aliases into a canonical identity — so these defaults can never silently regress.
- **README "Works out of the box" section** — makes the zero-config defaults (PDF, entity
  resolution, hybrid retrieval, opt-in LLM) explicit up front.

### Fixed
- **`--llm-extract` no longer silently runs L4 community summaries.** It was coupled to
  `llm_enabled`, so `build --llm-extract` also produced `SUMMARIZES` (GENERATED) edges — the
  build summary reported only the extraction count (e.g. "24 LLM relations") while the graph
  held more GENERATED edges (e.g. 33), which read as a miscount. Extraction is now gated on
  `llm_extract` alone (independent of the summaries switch), so `--llm-extract` adds only
  cited extraction relations and the reported count **equals** the GENERATED edges it added.
  Community summaries stay on `--llm`; the build summary now reports both counts separately.

## [3.3.1] - 2026-08-08

### Changed
- **Positioning/description refreshed** across PyPI summary, `README`, `__init__`, and the
  demo landing page: leads with **deterministic & local-first by default**, now explicitly
  naming the **opt-in LLM extraction, grounded answer synthesis, and semantic (embedding)
  search** added in 3.2 (all `GENERATED`-quarantined). Replaces the outdated
  "zero-LLM-by-default" phrasing that under-sold the LLM capabilities. No code changes.

## [3.3.0] - 2026-08-08

**Semantic-web interop — closing the RDF / ontology gap with polyglot peers.** New
deterministic, dependency-free exports so the graph loads into any triple store and
validates in any semantic-web toolchain.

### Added
- **RDF/Turtle export** — `textgraph export --format rdf` emits the whole graph as Turtle
  (loads into Oxigraph / Apache Jena / RDF4J / any SPARQL store): nodes typed by their
  labels, relations as `tgr:` predicates, and **every cited edge reified as an
  `rdf:Statement`** carrying the `ConfidenceTag` + the re-verifiable byte span
  (`prov:wasDerivedFrom`, `tgo:sourceStart/End/Hash`) — provenance survives the round-trip
  (G3). Validated with rdflib; pure-string, no RDF dependency.
- **OWL vocabulary export** — `--format owl` emits `owl:Class` per node label,
  `owl:ObjectProperty` per relation predicate (with induced `rdfs:domain`/`range`), and
  `owl:DatatypeProperty` per scalar key.
- **SHACL shapes export** — `--format shacl` emits a `sh:NodeShape` per class with
  constraints (label cardinality, per-predicate `sh:class`) **induced from the actual data**
  — validate the graph in pySHACL / TopBraid / Jena.

All four export formats (`rdf`, `owl`, `shacl`, `prov-o`) are byte-deterministic (G1).

## [3.2.1] - 2026-08-08

**Packaging & presentation polish** (no code/API changes). Makes the PyPI page and repo
look the part next to [Semantica](docs/COMPARISON_SEMANTICA.md).

### Added
- **`LICENSE`** file (MIT) — so the license is detectable on GitHub and shipped in the sdist.
- **PyPI project metadata** — `[project.urls]` (Homepage / Repository / Documentation /
  Changelog / Live demo / Bug Tracker → the PyPI sidebar) and trove `classifiers` (Python
  versions, MIT, audiences, topics), plus `license-files`.
- **README** — a compact **TextGraph vs. Semantica** section (where TextGraph leads: byte-
  identical builds, re-hashable citations, zero-LLM core; and the honest roadmap: RDF store,
  OWL/SHACL, more providers/vector stores). A **Python-API** quick start alongside the CLI.

### Fixed
- **Broken README badges** — the CI badge pointed at a non-existent `ci.yml`; replaced with
  working **tests** + **determinism** workflow badges and an MIT license badge.

## [3.2.0] - 2026-08-08

**TextGraph 3.2 — LLM-augmented intelligence, without losing the moat.** Adds semantic
retrieval and opt-in LLM assistance for both **input** (extraction) and **output** (answers),
benchmarked against [Semantica](docs/COMPARISON_SEMANTICA.md). Every addition is **opt-in and
quarantined** — the deterministic-by-default build (byte-identical `graph.json`), byte-level
provenance, and zero-LLM default are all untouched.

> **Note:** the PyPI distribution is now **`textgraph-kg`** (`pip install textgraph-kg`); the
> import package and CLI remain `textgraph`. (`textgraph` was already taken on PyPI.)

### Added
- **Dense semantic retrieval.** A third, *semantic* signal fused into the existing BM25 +
  Personalized-PageRank RRF blend. Backends behind one interface: `openai` (OpenAI-compatible
  `/embeddings` — local **Ollama `nomic-embed-text`**, vLLM, or OpenAI, dependency-free), `st`
  (local `sentence-transformers`, `[embed]` extra), and `hash` (deterministic, model-free). A
  persistent disk cache means only cache-misses hit the model. **Query-time only — never enters
  `graph.json`**, so determinism (G1) is unaffected. `textgraph query … --embed openai`.
- **LLM relation extraction (input).** `build --llm-extract` runs the LLM (default: NVIDIA
  **Nemotron** via vLLM, `client.DEFAULT_LLM_MODEL`) over chunks to add `GENERATED`-tagged
  relations the deterministic extractors miss — each cited to its chunk, bounded by a call
  budget (G7), prompt-cached. Off by default, so the default build has zero `GENERATED` edges
  and the determinism/provenance gates are untouched.
- **LLM answer synthesis (output).** `query --narrate` composes a fluent, **cited** answer
  strictly from the retrieved evidence — tagged `GENERATED`, instructed to abstain when the
  evidence is insufficient, and always shown next to its re-verifiable citations.
- **`docs/COMPARISON_SEMANTICA.md`** — an honest TextGraph-vs-Semantica comparison.

## [3.1.0] - 2026-08-08

**TextGraph 3.1 — the decision-provenance & conflict release.** On top of v3.0's interactive
surface, 3.1 makes the graph *accountable*: it models **decisions** as a first-class causal
layer, detects and (optionally) resolves **conflicting claims** without ever silently merging
them, exports an interoperable **PROV-O** audit trail, and adds a first-run **doctor**. All of
it preserves the moat: **deterministic build (byte-identical `graph.json`), byte-level
provenance, zero-LLM-by-default, local-first.**

Highlights:
- **Decision objects + causal chains** — `WHY`/`DECISION`/`RATIONALE`/`ADR-N` become
  `Decision` nodes with `CAUSED`/`INFLUENCED`/`PRECEDENT_FOR` edges; `trace-decision` walks a
  decision's lineage (what led to it, what it led to) and `find-decisions` searches them —
  all cited.
- **Conflict detection & resolution** — single-truth disagreements are surfaced as
  `Conflict` nodes (never a silent merge); opt-in `most_recent`/`voting`/`credibility_weighted`
  resolution demotes losers non-destructively (`SUPERSEDED_BY`, keeping citations).
- **PROV-O export** — `textgraph export --format prov-o` emits a W3C PROV-O JSON-LD trail.
- **`textgraph doctor`** — read-only environment + on-machine determinism health check.
- **Console** — a `graph.json` "Save snapshot" export, and the Ask chat now routes to the
  conflicts / trace / find-decisions tools with inline cited detail.

### Added
- **Console "Ask" chat routes to the decision/conflict tools.** Natural-language questions
  now reach `conflicts`, `trace` (decision chain), and `find-decisions`: "are there
  conflicts", "what led to this decision", "find decisions about retention". The chat renders
  the causal chain and conflict list inline (relation, direction, resolution) with citation
  chips, and new tool chips are selectable directly. `"conflict"` and `"contradiction"` now
  route to their distinct tools. Tracing a body decision promotes to its ADR record so the
  full lineage always surfaces.
- **Decision-chain traversal + similarity (`trace_decision_chain`, `find_similar_decisions`).**
  `QueryEngine.trace_decision_chain(decision)` walks a decision's causal lineage — backward
  over `CAUSED`/`INFLUENCED`/`PRECEDENT_FOR` for **what led to it** (precedents/causes) and
  forward for **what it led to** (effects) — as ordered, cited, cycle-safe, depth-bounded
  hops. `QueryEngine.find_similar_decisions(query)` ranks `Decision` nodes by BM25 relevance
  of their statement text, each hit cited to its source span. New `textgraph trace-decision`
  and `textgraph find-decisions` CLI verbs; both are security-aware (a decision whose source
  is unauthorized never surfaces). Causal linking now attributes an in-body ADR reference to
  the document's ADR record, so ADR-level lineage stays connected end to end.
- **Conflict detection (truth discovery) — a first-class step, never a silent merge.**
  When two sources make incompatible claims about the same entity on a *single-truth*
  predicate (`CONTROLS`, `BENEFICIAL_OWNER_OF`, `DIRECTOR_OF` by default) — same subject
  (after `SAME_AS`), different objects, **overlapping validity windows** — TextGraph now
  surfaces a first-class `Conflict` node (severity-tagged) with cited `CONTENDS` edges to
  every contending claim. Detection is deterministic and **only surfaces** the conflict;
  it never picks a winner or deletes a claim (G3). The bi-temporal check means a legitimate
  sequential change (director of Beta in 2019, of Gamma in 2021) is *not* flagged, while
  genuinely contemporaneous claims are. New `textgraph conflicts` CLI verb,
  `QueryEngine.conflicts()`, a **Conflicts** section in `GRAPH_REPORT.md`, and
  `Config.detect_conflicts` / `Config.single_truth_predicates`.
- **Conflict resolution (opt-in, pluggable, never destructive).** With
  `build --resolve-conflicts <strategy>` (or `conflicts --resolve <strategy>`), TextGraph
  picks a winning object per conflict and **demotes** the losing claims — they gain
  `superseded_by` / `resolved_by` properties and a cited `SUPERSEDED_BY` edge to the
  winner, but are **never deleted** (G3). Three deterministic strategies: `most_recent`
  (latest in-text validity date; undated ⇒ honestly left unresolved), `voting` (most
  distinct sources, ties broken by earliest source), and `credibility_weighted` (summed
  per-source `Config.source_credibility`, defaulting to 1.0 so it degrades to voting).
  `SUPERSEDED` is an orthogonal marker, **not** a fifth `ConfidenceTag` tier — the four-tier
  taxonomy and the provenance gate are untouched. Resolution is config-pinned, so
  `graph.json` stays byte-identical.
- **Decision objects — a queryable causal layer over `Rationale`.** Decision-worthy L1
  markers (`WHY`/`DECISION`/`RATIONALE`/`ADR-N`) are promoted into first-class `Decision`
  nodes (category, statement, byte-span citation), each linked back to its rationale via a
  cited `DERIVED_FROM` edge. Author-controlled **causal edges** — the narrow, agent-legible
  trio `CAUSED` / `INFLUENCED` / `PRECEDENT_FOR` — are inferred from explicit in-text ADR
  references (e.g. `DECISION: … SUPERSEDES ADR-0007`). Deterministic, cited, and default-on;
  disable with `Config(derive_decisions=False)`. (Automated `trace_decision_chain` /
  `find_similar_decisions` remain future work — they depend on L6/L8.)
- **PROV-O export** — `textgraph export --format prov-o` emits a W3C PROV-O **JSON-LD**
  decision-provenance trail: `Decision → prov:Activity`, source `Document → prov:Entity`
  (`prov:used`), the extractor → `prov:SoftwareAgent` (`prov:wasAssociatedWith`), and the
  causal edges → `prov:wasInformedBy` (effect informed by cause). Byte-range citations ride
  along as `textgraph:sourceSpan`. Dependency-free and byte-stable.
- **`textgraph doctor`** — a read-only environment health check for first-time triage.
  Checks Python version, temp-dir writability, core/optional extras (`[ingest]`, `[ie]`,
  `[er]`, `[graph]`, DuckDB), and — the marquee check — **on-machine determinism**: it
  builds a tiny corpus twice and asserts a byte-identical `graph.json`, confirming the
  exact guarantee CI enforces. Human-readable by default; `--json` for CI preflight gates;
  `--check <name>` runs one named check in isolation. No `--fix` (read-only by design).
- **Console graph.json export** — a read-only "Save snapshot" button in the console
  downloads a canonical `graph.json` of the current graph (reflecting any in-UI ingest).
  A corpus-directory console rebuilds from source for a complete artifact (with the `docs`
  manifest); a `.duckdb`/snapshot console serializes the live engine's nodes + edges via
  `export_graph_bytes`. Served at `GET /api/export`; deterministic and byte-canonical.
  Hidden on the offline `graph.html` (no server).

## [3.0.0] - 2026-08-06

**TextGraph 3.0 — the interactive + investigator-defaults release.** On top of the v2.0.0
enterprise extensions, 3.0 adds a grounded conversational surface and acts on a competitive
market review — making the highest-leverage capabilities the *default*, proving quality
honestly, and hardening for real use. All of it preserves the moat: **deterministic build
(byte-identical `graph.json`), byte-level provenance, zero-LLM-by-default, local-first**.

Highlights:
- **Console "Ask" chat** — ask in plain English; routed to the right graph tool, answered
  **cited**, with the answer highlighted on the graph, a collapsible reasoning chain,
  multi-turn follow-ups, **grounding confidence + abstention**, and opt-in **file-attach
  ingestion** into the live graph. Plus a redesigned, spacious, theme-aware UI.
- **Investigator defaults** — **PDF text ingestion is now built-in** (pypdf → core), entity
  resolution confirmed on-by-default, and the `[ie]` GLiNER backend runs **int8-quantized
  ONNX** for usable CPU speed.
- **Retrieval & integrations** — documented query routing, **LangChain / LlamaIndex adapters**
  that keep byte-span citations, and a Neo4j scale-out **design** (DuckDB stays default).
- **Proof & honesty** — an extraction-quality benchmark that **publishes the hallucinated-edge
  rate (0.167)** and an honest peer comparison; grounding/abstention ("insufficient evidence").
- **Ops hardening** — a provenance/SAME_AS/invalidation **admin inspector**, incremental
  reindex stress + partial-write recovery, and optional console **token auth** + ingest lock.

Breaking-ish: `pypdf` is now a core dependency (installs by default). Full per-item detail
below.

### Changed — positioning leads with the differentiators (Sprint 4.4)
- **README** now opens with a **"Why it's different (vs GraphRAG)"** section that leads with
  the real edge — *deterministic* (byte-identical `graph.json`), *byte-level provenance* (100%
  re-verified), *zero-LLM-by-default*, *bi-temporal versioning*, and a *published
  hallucination rate* — instead of generic "GraphRAG" framing, and states plainly that
  local-first/DuckDB is the default with Neo4j only an optional scale-out backend. These are
  the axes the market scan found TextGraph actually wins on and had been under-selling.

### Hardened — console server concurrency + optional auth (Sprint 4.3)
- **Ingest serialization:** the file-attach rebuild + engine hot-swap is now guarded by a
  lock, so two concurrent uploads can't race. Reads stay lock-free (an engine swap is a
  single atomic reference assignment under the GIL — a reader sees the old or new engine,
  never a torn one); the concurrency model is documented on `_State`.
- **Optional bearer-token auth:** `textgraph console … --token <T>` requires the token on
  `/api/*` (via `Authorization: Bearer` or `?token=`) while still serving the page — recommended
  before binding a non-localhost `--host`. Verified live (401 without, 200 with). *Flagged as
  future:* async indexing jobs and full multi-user identity are out of scope for this pass
  (they would need a job queue / user store); the token is basic per-instance auth.

### Added — graph inspection / provenance admin view (Sprint 4.1)
- **`QueryEngine.inspect(node)` + `GET /api/inspect`** — the "admin console" detail most
  GraphRAG tools lack: for any node, its re-verifiable **provenance** spans, the **confidence
  tier** histogram of its relations (`EXTRACTED`/`INFERRED`/…), its non-destructive
  **SAME_AS** cluster (canonical + members), and each claim's **validity window /
  supersession** history. Access-controlled like the other tools. The console inspector now
  renders these sections when a node is clicked; the offline `graph.html` falls back to
  `why()` gracefully. +1 test.

### Hardened — incremental reindex stress + partial-write recovery (Sprint 4.2)
- **`DocIECache.get()` now recovers from a corrupt / partially-written cache entry** (a crash
  mid-write leaving truncated JSON): it's treated as a miss, the poisoned file is dropped, and
  the document is re-extracted — a bad cache never fails a build (G5). +4 stress tests: after
  deleting or modifying a document, an incremental rebuild is **byte-identical** to a clean
  full rebuild; a poisoned cache recovers to the identical graph.

### Added — extraction-quality benchmark + honest peer comparison (Sprint 3.1 / 3.2)
- **`benchmarks/quality.py`** — measures the extracted graph against a hand-labelled gold set
  on the `docs` fixture: entity P/R/F1 (**1.0/1.0/1.0**), asserted-relation P/R/F1
  (**0.833**), **false / hallucinated edge rate (0.167 — reported, not hidden)**, and
  **citation coverage (1.0)**. It credits the extractor for correctly tagging *negated*
  relations (`polarity=neg`) and names its one honest weakness (a coreference error). Gated
  by `tests/integration/test_quality_benchmark.py` so quality can't silently regress.
- **`BENCHMARKS.md`** gains the quality numbers and an **honest peer comparison** vs Graphiti
  / LightRAG / HippoRAG / Neo4j GraphRAG Python: a *capability* table on the axes that differ
  (byte-level provenance, deterministic build, zero-LLM-default, measured hallucination rate,
  bi-temporal versioning), with an explicit statement that a fair *head-to-head QA* comparison
  isn't feasible yet (peers are LLM-driven/non-deterministic) — no fabricated numbers.

### Added — answer-grounding confidence + abstention (Sprint 3.3)
- **`textgraph/l8_retrieval/grounding.py`** — the "Ask" chat now scores how well each answer
  is supported by citation evidence and **abstains** ("Insufficient evidence in the graph to
  answer that confidently.") instead of surfacing an unsupported guess. Deterministic and
  pure: non-factual aggregates (stats/communities/contradictions/gql) are always confident;
  factual answers (search/why/path/neighbors/timeline/reason) with **zero citations** abstain,
  and confidence rises with the number of distinct cited spans. `ChatAnswer` gains
  `confidence` + `abstained`, surfaced in the UI as a "N% grounded" / "abstained" badge. +4 tests.
- *Audit note:* the retrieval PPR is **already query-conditioned** — `search` personalizes the
  PageRank teleport from the query's named entities + top lexical chunks (`personalization=seed`
  in `l7_analytics.algorithms.pagerank`), so a query-specific walk was in place since Phase 4;
  Sprint 3.3's new contribution is the grounding/abstention layer on top.

### Added — LangChain / LlamaIndex adapters, citations preserved (Sprint 2.5)
- **`textgraph/integrations/`** — consume the TextGraph graph from LangChain and LlamaIndex
  **without dropping byte-span provenance**. Pure converters (`search_to_documents`,
  `search_to_nodes`) map a `SearchResult` to `Document`/`TextNode`-shaped payloads that carry
  every `[doc:start-end]` citation in `metadata` (G3 preserved). Framework retriever classes
  (`make_langchain_retriever`, `make_llamaindex_retriever`) subclass each framework's
  `BaseRetriever`, import-guarded behind the new `[langchain]` / `[llamaindex]` extras (clear
  `UnsupportedFormat` without them). +4 tests (converters + citation preservation + fallback).
- **G3 verified, not assumed:** both `Document.metadata` and `TextNode.metadata` are free-form,
  so neither framework forces dropping citations — the adapters ship. Flagged in the module:
  if a framework required opaque metadata-less chunks, that would violate G3 and we would not
  ship its adapter.

### Design — optional Neo4j scale-out backend (Sprint 2.4, `docs/plans/neo4j-backend.md`)
- Design (no code) for an **opt-in** `textgraph serve --backend neo4j` that *materializes an
  already-built `graph.json`* into Neo4j for scale — the DB is a downstream query target,
  never the source of truth or part of the deterministic build, so G1/G2/G3 are preserved and
  **DuckDB stays the default**. Compared feature-by-feature against Neo4j GraphRAG Python
  (VectorCypherRetriever, ToolsRetriever, GraphPruner, EntityResolver, schema-guided
  extraction, lexical graph, Cypher 25 `SEARCH`): adopt the retrieval-shape patterns; reject
  as *defaults* the ones that push LLMs/non-determinism into the build. Recommends building a
  read-only Neo4j loader/query backend behind `[neo4j]` first.

### Added — documented per-query retrieval routing (Sprint 2.2)
- **`textgraph/l8_retrieval/routing.py`** — one deterministic, ordered rule set that maps a
  question to a retrieval *tool* (`classify_query`) and a *strategy family*
  (`route` → `RoutePlan{tool, strategy, reason}`): structured-graph (GQL), graph-traversal
  (path/neighbors/why/timeline), graph-analytics (communities/contradictions/stats),
  hybrid-lexical-graph (`search` = BM25 + Personalized PageRank + RRF), hybrid-multi-tool
  (`reason` = Graph-of-Thoughts). The console "Ask" chat now shares this single source of
  truth (its inline `classify` was promoted here), so routing can't drift between surfaces.
  Rules documented in `docs/retrieval-routing.md`; the `reason` string is surfaced for
  auditability (G6). +4 tests.
- *Audit note:* Sprint 2.1 (L6 bi-temporal Claims, L7 analytics — communities/god-nodes/
  bridges/contradictions, L8 hybrid BM25+PPR+RRF with local/global routing) and Sprint 2.3
  (multi-hop max-likelihood **k-shortest path ranking**, Yen's algorithm, every step cited)
  shipped in Phases 4–10 and are covered by existing tests — confirmed complete, not re-done.

### Changed — PDF ingestion is now a default capability (Sprint 1.1)
- **`pypdf` moved from the `[ingest]` extra into the core dependencies**, so `textgraph build`
  ingests PDF text out of the box — investigators live in PDFs, and gating that behind an
  extra was an adoption barrier. `pypdf` is pure-Python, BSD-3 licensed, small, and
  deterministic (no binary deps, no GPU), so it doesn't compromise the lean, local-first
  default (G2) or determinism (G1). Higher-fidelity **layout / table / OCR** extraction
  (Docling) stays opt-in in `[ingest]`. `requirements.txt` gains `pypdf`; README "Supported
  formats" updated. +1 test (`test_pdf_ingests_by_default`, a self-contained minimal PDF).

### Changed — GLiNER backend runs int8-quantized ONNX on CPU (Sprint 1.3)
- **The `[ie]` GLiNER backend now loads the int8-quantized ONNX model by default** (new
  `Config.ie_onnx=True`), the well-known fix for GLiNER's punishing CPU latency (minutes per
  handful of chunks on the fp32 torch path). `load_model()` prefers `onnx/model_quantized.onnx`
  and falls back to the torch weights if that file isn't published for the pinned model — so
  higher-recall extraction is finally usable without a GPU.
- **Wired the backend properly** (it was a stub): GLiNER now supplies the NER *mentions*, and
  relations are built by the **same deterministic extractor the rule backend uses** — the
  relation/coref/predicate logic was factored into a shared `assemble_ie()` (byte-identical to
  before; the determinism gate proves it). So recall goes up with **no new nondeterminism**,
  and the `IEResult` shape is unchanged.
- CI honesty: `[ie]` + a downloaded model aren't in the lean CI, so the model-load/NER lines
  are `# pragma: no cover` and must be validated on a machine with the extra; the pure pieces
  (prediction→mention mapping, availability, fallback) are unit-tested. +3 tests. The default
  **rules** backend and the byte-identical `graph.json` are untouched.

### Confirmed — entity resolution is on by default (Sprint 1.2)
- **L5 entity resolution already runs in every `build()`** with the deterministic **rules**
  backend (`Config.resolve_entities=True`, `er_backend="rules"`) — no extra, no flag —
  collapsing aliases (`Acme Corp` / `Acme Corporation` / `ACME`) to a canonical node via
  **non-destructive** `SAME_AS` edges. Added a pipeline-level test pinning this default-on
  contract (default build emits `SAME_AS` + a `Canonical` node; `resolve_entities=False`
  removes them); `textgraph er audit` verified working.
- **Flagged (G2 conflict, not implemented):** the backlog asked to make **Splink** the
  default ER step, described as "no new heavy dependencies." It is not — Splink pulls in
  `splink` + `duckdb` + `pandas`, which would bloat the lean local-first default and trade
  away the moat the market review says to protect. The deterministic rules backend already
  delivers default-on resolution; **Splink stays the opt-in `[er]` backend.** Quality
  improvements to alias/synonym handling are tracked for Sprint 3.

### Added — console "Ask" chat (grounded, deterministic)
- **A chat dock in `textgraph console`.** Ask a question in plain English; it is *routed* to
  the right graph tool (reason / search / path / why / neighbors / timeline / contradictions /
  communities / stats / gql) and answered with a **templated, cited** reply that also
  **highlights the answer's nodes and path on the graph beside it**. Every reasoning step is
  shown as a collapsible thought-chain artifact, and each fact carries its `[doc:span]`
  citation — no LLM, fully deterministic and offline (G1/G2/G3).
- **Multi-turn, stateless server:** follow-ups ("why?", "who controls it?") resolve their
  missing entity against the previous answer's focus, passed by the client. New pure
  `textgraph/console/chat.py` (`answer()` + intent `classify()`), a `POST /api/chat` route,
  and `do_POST` on the console server. The offline `graph.html` (no server) hides the dock
  gracefully. +8 tests.
- **Attach files to the graph** (opt-in `textgraph console --allow-ingest`): drop documents
  into the chat and they are ingested into the **live** graph — written into the corpus dir
  (basename-only, extension-allowlisted, size-capped) and **incrementally** rebuilt
  (`build(root, cache_dir=…)`, byte-identical to a clean rebuild), then the engine is
  hot-swapped and the canvas + stats refresh. New `textgraph/console/ingest.py` with a
  stdlib `multipart/form-data` parser (`cgi` was removed in 3.13), `POST /api/ingest`, and
  `/api/config` gating. Read-only stays the default; the attach control only appears when
  ingestion is enabled. +6 tests.

### Fixed — Graph-of-Thoughts access-control + cost (prerequisite for the chat)
- `GraphOfThoughts` now accepts an **injected engine** instead of always building its own, so
  it reuses the caller's already-built (and possibly policy-protected) `QueryEngine` — this
  avoids rebuilding the BM25/PPR indexes on every call **and** closes an access-control gap:
  `reason(..., context=…)` now threads a `SecurityContext` through every tool call, and
  `QueryEngine.resolve()` became **policy-aware**, so a restricted entity can no longer leak
  into a thought (e.g. via the Plan's focus list). The non-policy-aware `gql` corroboration
  is skipped under a context. +1 red-team test.

## [2.0.0] - 2026-08-06

**TextGraph 2.0 — the enterprise-extension release.** The deterministic L0–L9 core shipped
in v1.0.0; 2.0 adds four optional, flagged extension layers on top, each of which preserves
the byte-identical `graph.json` guarantee (G1) and the local-first, zero-LLM-by-default
posture (G2) — with no policy / no query they change nothing about the default install:

- **Phase 7 — GQL / ISO-GQL standards query surface** (`textgraph/gql/`, `textgraph gql`)
- **Phase 8 — vision-native late-interaction (MaxSim) retrieval** (`[vision]`, `textgraph vision`)
- **Phase 9 — enterprise fine-grained access control** (`[security]`, `textgraph secure`)
- **Phase 10 — Graph-of-Thoughts agent reasoning** (`textgraph/got/`, `textgraph reason`)

The full L0–L10 stack is now complete. Per-phase detail follows.

### Added — Phase 10: Graph-of-Thoughts agent reasoning (`textgraph/got/`)
- **A KG-grounded reasoner (ESCARGOT-style).** `GraphOfThoughts.reason(query)` builds a
  graph of thought vertices with roles (Plan / SubProblem / Hypothesis / VerificationStep /
  DistilledSummary, §4.1) using the four GoT operators — **Generation** (`neighbors`),
  **Aggregation** (`path`), **Refinement** (`why` + a `gql` triple check), **Distillation**
  (prune + summarise). Every substantive thought is **bound to real graph evidence**: its
  `[doc:start-end]` citations come from the tool that produced it, and a thought that
  gathered none is dropped — so the finished chain is verifiable end to end (G3).
- **Adaptive cost (DGoT/AGoT).** Task complexity — how many entities the query itself names
  — is measured at runtime. A simple query runs a cheap linear chain; only when complexity
  crosses a threshold does the loop spawn the parallel Aggregation/Refinement branches. A
  `static` mode expands the full topology regardless, as a baseline. The tool-call budget
  is hard-bounded (G7).
- **Deterministic and read-only.** Every tool it calls is deterministic and sorted, thought
  ids are sequential, and there is no wall-clock or randomness — reasoning is reproducible
  (G1) and never touches `graph.json`.
- **CLI:** `textgraph reason <corpus|.duckdb> "<question>" [--mode adaptive|static]` prints
  the whole cited reasoning chain, its tool-call cost, and the grounded answer.
- **DoD — cited steps + a number:** `benchmarks/reasoning.py` shows the adaptive reasoner is
  **70% cheaper** than the static-topology baseline (24 vs 80 tool calls over the fixture)
  while **every reasoning step cites real graph spans** — see `BENCHMARKS.md`.
- +11 tests (thought model, the four operators end to end, complexity gating, adaptive <
  static, grounding invariant, determinism, CLI); coverage stays ≥ 88%.

### Added — Phase 9: enterprise fine-grained access control (`textgraph/security/`)
- **ReBAC + ABAC, enforced inside traversal.** A new `[security]`-flagged layer brings
  Relationship-Based Access Control (Zanzibar/OpenFGA-style relation tuples — `owner`,
  `viewer`, `member`, `parent`, usersets, with transitive group/folder policy paths) and
  Attribute-Based Access Control (Cedar-style `MinClearance` / `IpAllowlist` / `TimeWindow`
  conditions) to the graph engine (gap-analysis §3.1).
- **Security-aware Personalized PageRank (not a post-filter).** Attach a `SecurityPolicy`
  to a `QueryEngine` and pass a `SecurityContext` per tool call: retrieval runs on a graph
  **masked to the principal's authorized nodes**, so an unauthorized node's transition
  probability is `0` and can never influence centrality, seed a walk, or surface as a hit
  (§3.2). `path` prunes restricted nodes *and edges* mid-Dijkstra; `neighbors`, `why`,
  `timeline`, `contradictions`, `communities`, and `vision_search` are all context-aware,
  and an edge is hidden unless its own source document is authorized (no leaking a
  restricted relation between two otherwise-visible entities).
- **Deterministic default, service behind the extra** (the project's upgrade-or-fall-back
  rule): the built-in `RebacStore` is pure-Python and needs no service; a real OpenFGA /
  Zanzibar deployment is opt-in behind **`[security]`** via `resolve_policy_engine`,
  import-guarded with a clean fallback to `rebac`.
- **`graph.json` is untouched.** Access control is purely query-time — with no policy (or
  no context) every tool behaves byte-identically to the un-secured engine, so the default
  install and the deterministic artifact are unaffected (G1/G2).
- **CLI:** `textgraph secure <corpus|.duckdb> "<query>" --policy policy.json --principal
  alice [--group G --clearance N --ip … --as-of DATE]` runs a search under a policy.
- **DoD — red-team + a number:** `tests/integration/test_security_redteam.py` proves
  **zero context-bleed** through PPR / paths / neighbors / summaries / vision (and that the
  leak is real without a policy); `benchmarks/security.py` measures the enforcement
  overhead (~+14% p50, full-access) and confirms transparency — see `BENCHMARKS.md`.
- +33 tests (ReBAC reachability incl. nesting/inheritance/usersets/cycles, ABAC rules,
  policy assembly, `[security]` fallback, the red-team suite, CLI); coverage stays ≥ 88%.

#### Phase 9 review — two security fixes
- **`stats()` no longer leaks unauthorized entity names.** It was the one agent tool left
  un-scoped, so a restricted (e.g. high-PageRank) entity's name and community label could
  surface through `top_entities` regardless of the caller's policy. `stats` now takes a
  `context` and computes its counts and `top_entities` over authorized content only
  (red-team assertion added; the unsecured control still surfaces them).
- **ABAC `MinClearance` now fails closed on an unmapped classification.** A document
  carrying a classification label absent from the `levels` map previously defaulted to
  level 0 (public) — silent privilege escalation on a misconfigured policy. A classified
  (non-empty, unmapped) label is now denied; an unclassified (empty) resource stays public.

### Added — Phase 8: vision-native late-interaction retrieval (`textgraph/l8_retrieval/vision/`)
- **ColPali-style page retrieval, MaxSim and all.** A query and a document-as-**page** are
  each a **multi-vector**, scored by the late-interaction **MaxSim** operator
  `sum_i max_j (q_i · p_j)` (gap-analysis §2.1). The engine gains `vision_search()` /
  `textgraph gql`-sibling `textgraph vision "<query>"`, ranking pages by MaxSim.
- **Deterministic default, model behind the extra** (the project's upgrade-or-fall-back
  rule): the `hash` embedder maps tokens to fixed unit vectors (SHAKE-256, pure stdlib),
  so the whole late-interaction pipeline runs and is unit-tested reproducibly with **zero
  GPU** (G1/G2). `vision_backend='colpali'` requests a real ColPali/ColQwen model over
  rendered page images behind the **`[vision]`** extra — import-guarded, falling back to
  `hash` if absent.
- **`graph.json` is untouched.** Embeddings are computed at query time only; pages are
  documents (already seeding PageRank via their entity mentions), so the default install
  and the byte-identical artifact are unaffected — verified.
- **DoD — a benchmarked number:** `BENCHMARKS.md` now reports the vision channel next to
  text: on the fixture, MaxSim/hash page retrieval scores **recall@5 0.80** (vs 0.70 for
  text) at higher cost (196 vs 131 tokens/query, ~11 ms) — real quality *and* cost. The
  `[vision]` model is where image-native gains land (not CI-benchmarkable without a GPU).
- +7 tests (MaxSim math, deterministic embedder, retriever, engine `vision_search`,
  `[vision]` fallback); 244 total, coverage 89%.

### Added — Phase 7: GQL / ISO-GQL standards layer (`textgraph/gql/`)
- **A standard graph-query surface over the property graph.** A pure-Python,
  deterministic subset of **GQL (ISO/IEC 39075) / Cypher** — tokenizer + recursive-descent
  parser + executor — so enterprise agents can query TextGraph the way they query any GQL
  backend (Neo4j, Memgraph, Kùzu), not through a bespoke API. Runs against the *same*
  `(nodes, edges)` the L8 tools use; **read-only, so G1/G2/G3 are untouched** and
  provenance stays reachable via edge properties.
- **Supported:** property-graph pattern matching `(a:Label {k:v})-[r:TYPE]->(b)` in all
  directions; **quantified (variable-length) relationships** `-[:T*min..max]->` (loop-free,
  depth-capped, G7); `WHERE` with `= <> < <= > >= CONTAINS STARTS WITH ENDS WITH IN`,
  `AND`/`OR`/`NOT`; `RETURN` with properties, `type()`/`labels()`/`id()`, `count(*)`
  aggregation and `AS`; `DISTINCT`, `ORDER BY … ASC|DESC`, `SKIP`, `LIMIT`. Result rows are
  stably ordered (deterministic).
- **CLI:** `textgraph gql <corpus|graph.duckdb> "MATCH (a)-[:CONTROLS]->(b) RETURN a.name, b.name"`.
- **DoD met:** the pattern-based tools **round-trip** — `neighbors`, `path` (quantified
  pattern), and `contradictions` expressed as GQL return results matching the typed tools
  on a fixture.

### Fixed — Phase 7 review (GQL hardening)
- **Malformed integer clauses no longer crash.** `LIMIT 2.5`, `SKIP 1.5`, `*1.5..3` raised
  a raw `ValueError` (an uncaught traceback at the CLI); they now raise a positioned
  `GQLError`.
- **Reused variables are a join constraint.** `(a)-[*1..2]->(a)` used to rebind `a` to
  every reachable node (returning "any path"); it now correctly means a **cycle** — a
  repeated variable must bind to the same element (proper Cypher/GQL semantics).
- **Undeclared variables are rejected.** `MATCH (:Entity) RETURN n.name` (or `… IN foo`)
  silently returned rows of NULL; it now errors with `unknown variable(s) not bound by the
  pattern`, catching typos instead of hiding them.
- **Negative number literals** (`WHERE n.x > -1`) now parse.
- +4 regression tests; 237 total, coverage 89.5%.

### Changed — v1.1: retrieval quality + wider coverage gate
- **Hybrid search reranking (`l8_retrieval/rerank.py`).** The raw RRF fusion broke ties
  by node id, which (since `chunk:` < `entity:`) buried every answer-entity beneath every
  passage — so "who controls Gamma Holdings" didn't even return Acme Corp in the top 5. A
  second-stage reranker now scores each kind by fusion score + lexical overlap and
  **interleaves** entities with passages (the answer node and its evidence, alternating).
  On the fixture benchmark: **recall@5 0.60 → 0.70, MRR 0.29 → 0.80**, tokens/query 163 →
  131 — deterministic. A cross-encoder reranker is the opt-in `[rerank]` extra
  (import-guarded, clean fallback). `BENCHMARKS.md` regenerated.
- **Coverage gate widened from `core/` to the whole package** (`fail_under` 80 → 88;
  actual ~90%), omitting only the import-guarded backends and socket-bound servers that
  run in dedicated jobs. Closes the last v1.1 debt item.

### Added — interactive graph console (toward v1.1)
- **`textgraph console` is now a real graph viewer.** A hand-rolled, dependency-free
  HTML5 **canvas** renderer draws the graph the way an investigator expects: nodes
  coloured by L7 community and sized by PageRank, pan/zoom/hover, a **Communities
  sidebar** with per-cluster toggles + "Select All" (counts and colour dots), a
  **confidence-tag filter** (so `GENERATED` output is visibly quarantined), hybrid
  **search** that highlights matching nodes and lists cited passages, **click-to-inspect**
  (a node's cited claims with `[t_valid, t_invalid)` windows, superseded ones flagged),
  a **path** mode that traces the maximum-likelihood chain between two clicked nodes,
  and a **temporal slider** — scrub a date and superseded claims fade out (the edge's
  `[t_valid, t_invalid)` window drives it; the label turns red the moment a correction
  supersedes an assertion). Nothing else on the market visualizes bi-temporal
  invalidation — and here it falls straight out of the L6 model.
- **Deterministic server-side layout (`l7_analytics/layout.py`).** Fruchterman-Reingold
  with community-aware gravity, **hash-seeded (no RNG) and fixed-iteration**, coordinates
  rounded and baked onto entity nodes as `x`/`y`. `graph.json` stays byte-identical (G1);
  the browser only *draws* the precomputed layout, never runs physics. Bounded for large
  graphs (top-N by PageRank + induced edges, with a visible "showing N of M" note, G7).
- New `/api/graph` endpoint + `QueryEngine.graph_view()`; zero external requests (G2).
- **The offline `graph.html` artifact is now the same interactive viewer.** The canvas
  renderer, CSS, and skeleton live in one shared module (`console/renderer.py`) driven by
  a small `TG` adapter, so the live console and the emailed file **never drift**: the
  console feeds it over `/api`, and `graph.html` embeds the graph + per-node cited claims
  and runs **client-side** path (Dijkstra over `-log(confidence)`) and search — fully
  interactive with no server. Retires the old concentric-ring SVG stub.
  +3 tests (temporal windows, offline viewer, layout); 214 total.

## [1.0.0] - 2026-08-04

First stable release. TextGraph turns any text corpus into a deterministic, fully
provenanced knowledge graph and makes it queryable by agents and humans alike — the
complete L0-L9 layer stack (Phases 0-6):

- **L0-L1** deterministic ingest + structural spine; **L2-L3** encoder IE (entities +
  typed relations); **L5** non-destructive entity resolution.
- **L6** citable, **bi-temporal** claims — corrections *invalidate* rather than delete.
- **L7** pure-Python analytics (PageRank, communities, contradictions).
- **L8** HippoRAG-style dual-node retrieval: eight typed, bounded, **cited** tools over
  a hybrid BM25 + Personalized-PageRank engine, exposed identically via the CLI, an MCP
  server, and a local web **console**.
- **L4** opt-in LLM synthesis, `GENERATED`-tagged and quarantined; **off by default**.
- **L9** byte-stable `graph.json` + report/HTML/manifest; DuckDB persistence and
  incremental `watch` rebuilds.

Every non-generated edge carries a re-verifiable byte-range citation; `graph.json` is
byte-identical across rebuilds (CI-gated); the default path is local-first and
zero-LLM. 207 tests, strict types, determinism + provenance gates green.

### Added — Phase 6: local console + packaging
- **`textgraph console <path>`** — a dependency-free, read-only web UI over the L8
  `QueryEngine` (`textgraph/console/`): all eight typed tools (search / neighbors / path
  / why / timeline / contradictions / communities / stats) in the browser, each result
  cited, validity windows shown for temporal claims. Built on stdlib `http.server`; the
  page is self-contained (inline CSS/JS, no CDN, G2) and theme-aware. Serves a corpus or
  a persisted `.duckdb` snapshot. Routing is a pure `route()` function, unit-tested
  without a socket (+6 tests).
- **Packaging verified for ship:** wheel builds cleanly and bundles the new packages
  (`console`, `l4_llm_optional`, `store/duckdb_store`, `watch`) with the `textgraph`
  console-script entry point.

### Added — Phase 6: optional LLM pass (L4)
- **Model-authored community summaries, quarantined by tag.** Opt-in L4
  (`l4_llm_optional/`) asks an LLM to summarize the largest L7 communities using *only*
  the facts passed to it, and emits a `Summary` node + `SUMMARIZES` edges tagged
  **`GENERATED`** — so model output can never be mistaken for an extracted, cited fact
  (G4). Enabled with `textgraph build --llm`; **off by default**, so the determinism
  gate never sees an LLM and `graph.json` stays byte-identical (G1, G2).
- **Dependency-free, OpenAI-compatible client** (`client.py`, stdlib `urllib`): works
  against OpenAI, vLLM, Ollama, or any `/chat/completions` endpoint via `base_url`. The
  **API key is read from the environment only** (`API_KEY` / `TEXTGRAPH_LLM_API_KEY` /
  `OPENAI_API_KEY`) — never stored on `Config`, hashed into `config_hash`, or written to
  an artifact. An unconfigured `--llm` build skips L4 rather than failing.
- **Hard-budgeted + cached** (`cache.py`, G7): at most `llm_max_calls` communities are
  summarized (biggest first), and responses are cached by a content hash of
  `(model, system, user, params)` so a warm rebuild is reproducible and free.
- `manifest.json` gains an `L4` stage + `summaries` coverage and reflects `llm_enabled`.
  +8 tests (mock client, no network); 200 total.

### Added — Phase 5: temporal + incremental
- **Bi-temporal claims (L6) — invalidation, not deletion.** When two claims about the
  same `(subject, predicate, object)` disagree in polarity, the later-dated one
  *supersedes* the earlier: the earlier claim's `t_invalid` is closed to the later
  claim's `t_valid`, and a cited `SUPERSEDES` edge records the correction. The
  superseded claim stays in the graph, so an agent can still ask *what was believed
  true, and when it changed* (`l6_graph_model/temporal.py`). Ordering uses only
  **valid-time dates stated in the corpus** (compared lexically — ISO dates sort
  chronologically); no wall-clock (G1). An undated conflict can't be ordered, so it's
  left open and still surfaces via L7 `CONTRADICTS`. `ClaimView` gains `t_invalid` +
  `status`; `timeline` / `why` / `contradictions` and `textgraph explain` show the
  `[t_valid, t_invalid)` window. New `invalidate_claims` config flag.
- **Persistent `DuckDBGraphStore`** (`store/duckdb_store.py`, behind `[graph]`/`[er]`).
  Import-guarded; serializes the assembled graph to a DuckDB file with an **exact**
  Node/Edge round-trip, so a graph **loads from disk without a rebuild**. `textgraph
  build --store PATH.duckdb` persists; any query verb given a `.duckdb` path loads it.
- **Incremental rebuild (G5).** `build(..., cache_dir=…)` caches per-document IE keyed
  by `(doc_id, config_hash)` (`core/incremental.py`), so editing one file re-extracts
  only that file — and the incremental build is **byte-identical** to a full build.
- **`textgraph watch <dir>`** (`watch.py`): content-addressed change detection (blake3,
  not mtime) triggers an incremental rebuild + artifact re-write; refuses an output/cache
  dir nested inside the watched corpus (would re-ingest its own artifacts).
- **CLI parity:** all eight L8 tools now have verbs — `neighbors`, `timeline`,
  `contradictions`, `communities`, `stats` join `query` / `path` / `explain`, over the
  same `QueryEngine` the MCP server uses.
- +17 tests (temporal, incremental, watch, DuckDB round-trip, CLI verbs); 193 total,
  determinism + provenance hold across the new `corpora/temporal` fixture.

### Added — Phase 4: Retrieval (L6 + L7 + L8 + MCP)
- **The graph is queryable.** Same `QueryEngine` drives the new CLI verbs
  (`textgraph query|path|explain`) and the MCP tool surface — an agent answers through
  typed tools alone, never raw Cypher (G6).
- **L6 claim reification (`l6_graph_model/claims.py`)** — every entity→entity relation
  edge becomes a first-class, citable `Claim` node (subject/predicate/object/polarity/
  modality/confidence) with a temporal window; the direct edge is kept. `t_valid` is
  grounded to the nearest `Date` in the same sentence (byte proximity); `t_invalid`
  stays null (full bi-temporal invalidation is Phase 5). No wall-clock in the graph.
- **L7 analytics (`l7_analytics/`)** — deterministic weighted **PageRank** + **Brandes
  betweenness** (`algorithms.py`), **label-propagation communities** with c-TF-IDF
  labels (`communities.py`), and diagnostics (`analyze.py`): **god nodes** (central on
  both measures), **bridges**, orphans, **contradictions**. `enrich.py` writes
  centrality/community onto entity nodes and emits `CONTRADICTS` edges between
  conflicting `Claim` nodes.
- **L8 retrieval (`l8_retrieval/`)** — HippoRAG-style **dual-node graph** (`Chunk`
  passage nodes + `chunk -[MENTIONS]-> entity` links, `emit_chunks.py`) with eight
  typed, bounded, cited tools (`engine.py`): `search` (pure-Python **BM25** in
  `bm25.py` fused with **Personalized PageRank** by **RRF**, local/global routing),
  `neighbors`, `path` (**maximum-likelihood**, Yen's k-shortest under `-log(confidence)`),
  `why`, `timeline`, `contradictions`, `communities`, `stats`. Every result is a
  token-budgeted context pack (`model.py`) with a `[doc:start-end]` citation on each row.
- **MCP surface (`textgraph/mcp/`)** — `tools.py` (specs + dispatcher, no `mcp`
  dependency, CI-tested) and `server.py` (stdio adapter behind the `[mcp]` extra).
- **First retrieval benchmark** (`benchmarks/retrieval.py`, `BENCHMARKS.md`) — recall@k
  / MRR reported *with* tokens-per-query and p50/p95 latency ("no number without its
  cost"); external LoCoMo/LongMemEval-S sets run only when data is present locally.
- **graph.json** now carries `Claim` nodes, `Chunk` nodes (with text), entity
  centrality/community properties, and `CONTRADICTS` edges — still byte-identical across
  rebuilds. `manifest.json` gains L6/L7/L8 stages + claim/community/contradiction/chunk
  coverage; `GRAPH_REPORT.md` gains Communities and Contradictions sections.
- **Tests:** L6/L7/L8/MCP unit suites + a tool-only **agent-session** integration test
  that verifies every answer's byte citations; 170 total. Determinism and 100%
  edge-provenance re-verification hold with L6–L8 in the loop, including a new
  opposite-polarity contradiction fixture.

### Fixed — Phase 4 review
- **`search` fabricated hits for no-match queries.** With an empty seed the Personalized
  PageRank teleport is uniform, so it re-emitted degree centrality — surfacing arbitrary
  entities for a query that matched nothing lexically or by name. Entity ranking is now
  gated on a real seed signal; a true no-match returns zero hits.
- **Dangling `CONTRADICTS` edges when reification is off.** `CONTRADICTS` links `Claim`
  nodes, so with `reify_claims=False` (L6 disabled) it pointed at nodes that don't
  exist. Emission now skips any pair whose claims aren't present in the graph.
- **`neighbors` buried relations under provenance edges.** `MENTIONS` / `HAS_CHUNK`
  (confidence 0.9) outranked real `TRANSFERRED` / `CONTROLS` relations (0.78); these
  membership edges are now hidden from `neighbors`, so semantic connections surface.
- **k-shortest paths were incomplete.** `path`'s Yen search discarded spur paths that
  looped through root nodes instead of routing around them; the spur Dijkstra now blocks
  root nodes, so genuine alternate paths are found.
- **Leiden was promised but not wired.** `analytics_backend="leiden"` now runs a real
  import-guarded Leiden pass (`igraph` + `leidenalg` behind `[graph]`) that raises
  `UnsupportedFormat` and falls back to the deterministic built-in when absent — matching
  the architecture's upgrade-or-fall-back pattern (the config field was previously dead).

### Added — Phase 3: Entity Resolution (L5)
- **Alias entities collapse to a canonical identity.** `Acme Corp` / `Acme
  Corporation` / `ACME` resolve to one canonical **"Acme Corporation"** node;
  `Beta Ltd` / `Beta Limited` → "Beta Limited"; unrelated `Alpha Bank` stays separate.
- **Blocking** (`blocking.py`): deterministic keys (suffix-stripped name, acronym,
  first-token), type-gated. Blocking recall gated ≥ 0.99 in CI.
- **Scoring** (`scoring.py`): Jaro-Winkler + token-set + acronym match + the
  graph-native **relational** shared-neighbour signal. Splink (Fellegi-Sunter on
  DuckDB) scaffolded behind the `[er]` extra.
- **Clustering** (`clustering.py`): complete-linkage agglomeration with a cohesion
  threshold — prevents the classic over-merge catastrophe (one bad edge merging two
  galaxies). Verified by a chain-merge unit test.
- **Non-destructive** `SAME_AS` lattice (`emit_er.py`): original entity nodes kept; a
  new `("Entity","Canonical",<etype>)` node links members via INFERRED, span-cited
  `SAME_AS` edges — fully reversible and auditable (§8.3).
- **`textgraph er audit`** command renders proposed merges with match scores for
  human review; **B-cubed metrics** (`metrics.py`) with a pinned F1 floor gated in
  CI; the god-node diagnostic flags an injected over-merge.
- **IE now runs per prose block** (not whole-doc text), so an entity can't span a
  heading→paragraph boundary; **acronym-of-known-org** detection links `ACME` to
  `Acme Corp`. Manifest reports canonical/SAME_AS/blocking counts; report gains a
  "Resolved entities (SAME_AS)" section; ablation shows the ER contribution.
- 133 tests, ~97% core coverage; determinism holds with L5 in the loop.

### Fixed — Phase 3 review
- **False Person from heading title-case** ("Corporate Aliases") — the person-bigram
  heuristic is disabled for headings, and `_PERSON_CUE` no longer uses global
  `IGNORECASE` (which had let "director on paper only" capture a lowercase "person").
- **ER over-merge: conflicting suffix families.** "Acme Bank" and "Acme Corp" (same
  base, different legal form) were merged by the suffix-stripped exact match. Added a
  `suffix_family` classifier; same-base names with conflicting families now score
  below the match threshold. Corp/Corporation, Ltd/Limited, Inc/Incorporated remain
  the same family, so true aliases still merge.
- **ER over-merge: shared suffix inflating similarity.** "Acme Corp" vs "Apex Corp"
  scored 0.867 (> 0.86) because the shared "Corp" lifted Jaro-Winkler over threshold.
  Name similarity is now computed on the suffix-stripped base name ("acme" vs "apex"
  → 0.70), so distinct companies no longer merge.

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

### Fixed — Phase 2 review pass
- **Coref coverage was double-counted.** `_Coref.resolve()` (used for relation
  slot-filling, called repeatedly per slot) incremented the same counters that
  `count_coverage()` uses, inflating `resolved/total` in `manifest.json`. `resolve()`
  is now a pure lookup; coverage is computed once over all pronouns.
- **Sentence segmenter treated org suffixes as abbreviations.** `Ltd.`/`Inc.`/
  `Corp.`/`Co.` were in the abbreviation list, so "...Beta Ltd. Acme Corp acted."
  never split — a run-on sentence that could misattribute relation subjects. Those
  suffixes (which routinely end sentences, unlike titles) were removed.
- **`MENTIONS` edges aggregated.** Instead of one edge per mention, each entity now
  has a single `MENTIONS` edge with `evidence_count` and all occurrence spans —
  surfacing repetition as a precision signal (§6.4) and shrinking the edge set.
- **Cross-document `mention_count`.** An entity appearing in several documents now
  reports its corpus-wide mention total, not just the first document's.

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
