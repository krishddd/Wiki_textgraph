# Structural role similarity — the design decision (Node2Vec vs. deterministic signatures)

**The user value:** *"find entities that play the same structural role as Acme Corp."* For
financial crime this is the shell-company detector — shells replicate a topological pattern (one
controller in, money out to several fronts, no inbound trade), so *role* similarity surfaces the
next shell even when its name and documents share nothing with the known one.

**The moat:** every build is byte-identical and reproducible (G1); nothing model-authored or
stochastic contaminates `graph.json`.

Node2Vec is the obvious tool and it is the wrong one here. This doc records why, and what we build
instead.

## Why not Node2Vec (as-is)

1. **It is stochastic twice over.** Node2Vec = biased *random walks* → *skip-gram* (word2vec).
   Both steps use RNGs; word2vec adds thread-nondeterminism (gensim is only reproducible with
   `workers=1` **and** a pinned `PYTHONHASHSEED`, which we cannot guarantee in a library). Two runs
   give different vectors, so "role similarity" would not be reproducible — the one property the
   whole project sells.
2. **It captures the wrong thing by default.** Vanilla Node2Vec embeds *proximity* (nodes near each
   other in the graph), not *role*. Two shells in unrelated cases are far apart, so a proximity
   embedding would rate them **dissimilar** — the opposite of what we want. Getting role out of
   Node2Vec needs struc2vec-style reweighting anyway.
3. **It is a heavy dependency** (gensim + numpy + a training loop) for a feature that must run on an
   analyst's laptop, CPU-only, offline — the same bar PDFs and entity resolution already clear
   without heavy deps.

## What we build instead: deterministic structural signatures (RolX/struc2vec-flavored)

A node's **role signature** is a fixed vector of *local topology invariants* — quantities that
describe the shape of a node's neighborhood, independent of *which* specific nodes it connects to.
Two nodes with similar signatures play a similar structural role, wherever they sit in the graph.

Per entity, deterministically computed from the graph we already have:

- **Degree** — in, out, total (a controller has high out / low in).
- **Weighted degree** — sum of incident edge confidences.
- **PageRank, betweenness** — already computed in L7 (centrality + brokerage).
- **Clustering coefficient** — do its neighbors connect to each other? (a hub-and-spoke shell ≈ 0).
- **Neighbor-degree stats** — mean/max degree of neighbors (points to hubs vs. leaves).
- **Relation-type profile** — normalized histogram over predicates it participates in
  (`TRANSFERRED`, `CONTROLS`, `DIRECTOR_OF`, …). This is the strongest role signal for the
  shell-company case: the *mix* of relations, not their targets.

**Role similarity** = cosine over z-score-normalized signatures. `similar_roles(Acme Corp)` returns
the entities whose local structure most resembles Acme's, ranked.

### Why this satisfies both the value and the moat

- **Deterministic & dependency-free.** Every feature is a sorted, closed-form function of nodes +
  edges — no RNG, no training, no threads, no new package. Reproducible by construction (G1).
- **Role, not proximity.** Signatures ignore *identity* of neighbors, so two shells in separate
  cases with the same shape score as similar — exactly the shell-detector behavior Node2Vec would
  miss. It also composes with **federation**: run role similarity across cases.
- **Query-time, artifact-free.** Like vision retrieval and embeddings, it reads the built graph and
  never writes `graph.json`, so the determinism/provenance gates are untouched.
- **Honest about scope.** This is not a learned embedding; it is an interpretable role vector. A
  true (opt-in, `[graph]`) Node2Vec/struc2vec backend can be added later for users who want learned
  embeddings and accept the reproducibility caveat — but the *default* stays deterministic.

## Plan (release 4.13.0)

| # | change |
|---|--------|
| 1 | `textgraph/l7_analytics/roles.py`: `structural_signatures(nodes, edges) -> {id: vector}` and `role_similarity(signatures, anchor, k)` (cosine over normalized vectors). Pure, deterministic. |
| 2 | `QueryEngine.similar_roles(entity, k)` — resolve the anchor, return ranked peers with their shared salient features (why they match). |
| 3 | CLI `textgraph roles <path> <entity> [-k N] [--json]`. |
| 4 | Console: a **"Similar roles"** Ask-dock tool + highlight the matches on the canvas. |
| 5 | Tests: determinism (same graph → identical ranking), role-not-proximity (two isolated shells with identical shape rank as similar), interpretable features. |

Deferred (own release, opt-in): a learned Node2Vec/struc2vec backend behind `[graph]`, seeded and
documented as best-effort-reproducible, for users who explicitly want it.
