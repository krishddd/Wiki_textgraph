# Graph Quality Audit — why the map reads as dots, and the plan to fix it

Audited against a real build: `C:/Users/hp/Downloads/case-out/graph.json`
(597 nodes / 1161 edges / 470 entities / 144 entity-entity relations / 266 communities).

The complaint — *"some dots are in space, some lines are just passing, many have no
relations"* — is not a rendering problem and not a tuning problem. It is **one ordering
bug in `pipeline.py`**, plus a namespace decision that follows from it, plus three UI
defaults that amplify the result. Everything below is measured, not inferred.

---

## The measurement

```
entities                        470
  etype Person 219 | LLM 153 | Date 44 | Money 41 | Organization 13
entity-entity relations         144
entities with >=1 relation      174        (37%)
orphans (degree 0)              296        (63%)
communities                     266        (240 of them size 1)

entities with x = y = 0         153        <-- no layout position at all
entities with pagerank == 0     153        <-- invisible to centrality
entities with community == -1   153        <-- never assigned a community
LLM-namespace entities          153        <-- the same 153, exactly
```

Those three "153"s are the whole story.

---

## F1 — Root cause: the LLM pass runs *after* resolution, analytics, and layout

`textgraph/pipeline.py`:

| line | step |
|------|------|
| 251 | **L5** entity resolution (SAME_AS) |
| 343 | **L7** `compute_analytics` — PageRank, betweenness, communities, **force layout** |
| 358 | **L8** chunk emission |
| **377** | **LLM relation extraction** ← *runs here* |

So every node the LLM contributes arrives **after** the only passes that would have
resolved, ranked, clustered, or positioned it. It is not that these 153 nodes scored
badly — they were never scored. `pagerank = 0`, `community = -1`, `x = y = 0`.

This single fact produces four of the six symptoms:

- **"Dots floating in space"** — 153 nodes at the origin with the minimum radius.
- **"Lines just passing"** — an edge is drawn between two nodes the layout never
  placed relative to each other, so it crosses the whole canvas as a long chord.
  `force_layout` (analyze.py:157) optimised positions for an edge set that *excluded*
  every LLM relation.
- **265 communities** — see F4.
- **No labels** — see F7.

## F2 — The `entity:LLM:` namespace guarantees duplicates

`l4_llm_optional/extract.py:58` mints ids as `entity:LLM:<key>` while the
deterministic path uses `entity:<TYPE>:<key>`. Two nodes for one real-world thing,
and ER (which already ran, F1) could not have merged them anyway.

Measured collisions on **exact lowercased name** alone — 23 of 153:

> `Admet LLC`, `Drive Planning`, `Del Villar`, `Del Entertainment`, `Calero Castro`,
> `Daniel Hooker`, `David Bradford`, `Esteban Hernandez`, `Gallistica Diamante`,
> `$811,000`, `$15 million`, `$24,628,943`, …

Fuzzy matching would find more. Each duplicate **splits a node's relations across two
dots**, which is a second, independent cause of apparent sparsity: the deterministic
`Drive Planning` holds the `MENTIONS` evidence, the LLM `Drive Planning` holds the
`TRANSFERRED` relation, and neither dot looks connected.

## F3 — "LLM" is a provenance stamp being displayed as an entity type

`extract.py:59` sets `etype: "LLM"`. That is *where the node came from*, not *what it
is*. The console legend reads it as a type, so 32% of the graph is typed "LLM" — which
is meaningless to an investigator. The node already carries `source: "llm"` for
provenance, and the edge already carries `ConfidenceTag.GENERATED` for quarantine, so
`etype` is doing no work here except misinforming the legend.

**The reviewer's read was directionally right, mechanism wrong**: it is not "the LLM" /
"an LLM" being extracted as separate mentions. It is a hardcoded stamp.

## F4 — 266 communities is arithmetic, not an algorithm bug

`communities.py:77` — label propagation skips nodes with no neighbours:

```python
if not adj.get(nid):
    continue  # isolate keeps its own initial label -> singleton community
```

With 296 of 470 entities at degree 0, 240 singleton communities is the **correct
output for that input**. There is no modularity/resolution parameter to tune (LPA has
none); the density is the problem. Fix F1/F2 and add F6, and this number collapses on
its own. The roster should also stop *listing* singletons.

## F5 — Co-occurrence exists, but only in the console

`l8_retrieval/engine.py:313` synthesises `CO_OCCURS` edges when the relation count is
low — but purely as a **view-layer decoration**. PageRank, communities, layout,
orphan detection and link prediction all run on the sparse 144-edge graph and never
see them. The console draws connections the analytics don't believe in.

## F6 — Orphans have no UI treatment

63% of what's on screen is degree-0 and there is no way to hide, fade, or count them.
The eye is drawn to noise instead of the structure.

## F7 — Labels are gated behind zoom, and the gate excludes the new nodes

`renderer.py:402` `rad = 3.5 + sqrt(pagerank) * 46`
`renderer.py:472` label drawn only when `rad * scale > 6`

A `pagerank = 0` node has radius 3.5, so it needs **1.72x zoom** before it is ever
labelled. Every LLM node is a pagerank-0 node (F1). The screenshots show exactly this:
a field of unlabelled small dots.

## F8 — "Ask the graph" is real (not a stub)

Verified: L8 retrieval shipped in Phase 4, `console/chat.py` dispatches to the real
`QueryEngine` across eight typed tools, with grounding/abstention. **No action needed**
— the reviewer's concern here does not hold.

## F9 — The screenshot difference is the time slider + layout settling

Screenshot 1 is `all time`; 2 and 3 are both `June 13, 2025` with the force layout at
different convergence points. Not a hover state. Worth a settle cue (F-C4), but not a
correctness issue.

## What is *right* — and is being buried

The relation vocabulary the pipeline actually extracted is exactly the project's
intent for case documents:

```
TRANSFERRED 10 | CHARGED 8 | LINKS_TO 7 | SOLD 6 | PLEADED_GUILTY 6
SENTENCED 6 | DIRECTOR_OF 6 | CONTROLS 5 | ASSOCIATED_WITH 5
```

That is a financial-crime narrative graph. The thesis is working. It is drowning in
296 unranked orphans and 153 unplaced duplicates.

---

# The plan

Four phases. **A is the fix**; B raises real density; C is perception; D stops the
regression. Moat rule held throughout: LLM output stays `GENERATED`-tagged, and a
build with the LLM off must stay byte-identical (G1).

## Phase A — one graph, one pass (release 4.7.0)

| # | change | file |
|---|--------|------|
| A1 | Move the `llm_extract` block from line 377 to **before L5 ER** (after the L3 merge, line 246) so LLM nodes flow through resolution, analytics and layout like every other node. | `pipeline.py` |
| A2 | Drop the `entity:LLM:` namespace — mint `entity:<key>` so LLM entities **merge by construction** with their deterministic twins; leave the rest to ER's fuzzy matching. | `l4_llm_optional/extract.py:58` |
| A3 | Stop writing `etype: "LLM"`. Inherit the twin's type on merge, else leave empty ("Unknown" in the legend). Provenance stays on `source: "llm"` + the `GENERATED` edge tag. | `extract.py:59` |
| A4 | Assert the invariant: **no entity may leave the pipeline with `community == -1` or an unset position.** | `pipeline.py` + test |

*Moat check:* merging node **identity** does not launder a `GENERATED` **edge** into
`EXTRACTED` — the tag lives on the edge, and G4 quarantine is unaffected. Determinism
is unaffected because the block is a no-op when `--llm-extract` is off.

*Expected on this corpus:* ~470 → ~447 entities; all 470 laid out and ranked; the
144 relations finally pull their endpoints together instead of drawing chords.

## Phase B — honest density (same release)

| # | change |
|---|--------|
| B1 | Promote co-occurrence from console-decoration to a **real, opt-in graph edge** (`--co-occurrence`), tagged `STRUCTURAL`, cited by the shared chunk span, so analytics/communities/layout actually see it. Single biggest lever on the community count. |
| B2 | Community roster: collapse singletons into one "N isolated entities" row instead of 240 rows. |
| B3 | Document `--analytics-backend leiden` as the quality upgrade now that density justifies it. |

## Phase C — make structure the thing you see first (release 4.8.0)

| # | change |
|---|--------|
| C1 | **Focus mode, on by default**: degree-0 nodes fade to ~8% with a toolbar toggle and a live "296 unconnected" chip. Structure first, completeness on demand. |
| C2 | Always label the **top 25 by PageRank** regardless of zoom, with simple collision avoidance; hover labels everything else. |
| C3 | Long-chord treatment: fade or curve edges whose length far exceeds the median, so cross-canvas lines stop reading as noise. |
| C4 | Layout settle cue (progress hint while the force layout converges). |
| C5 | Degree-aware radius: `rad = f(pagerank, degree)` so a relation-bearing node is never a 3.5px dot. |

## Phase D — a gate so this cannot come back (same release)

| # | change |
|---|--------|
| D1 | Extend `GRAPH_REPORT.md` + `textgraph doctor` with **graph-health metrics**: orphan %, singleton-community %, unlaid-node count, duplicate-name candidates. |
| D2 | Regression test: a fixture built **with** LLM extraction must have zero nodes at `pagerank == 0 / community == -1 / x == y == 0`. That test alone would have caught F1 at the moment it was introduced. |

---

## Sequencing

A → D2 first (fix, then lock it). B and C are independent and can ship together in the
same release. A is roughly a 40-line diff across two files and carries the majority of
the visible improvement.
