# TextGraph Benchmarks

> Discipline: **no number is reported without its cost.** Every accuracy figure is
> paired with tokens-per-query and p50/p95 latency, and every result ships with a
> reproduction command. Extrinsic benchmarks land in Phase 4.

## Reproducing

```bash
uv run python -m benchmarks.run --report benchmarks/latest-report.md
```

## Intrinsic metrics (available now)

Graph-health and determinism metrics on the fixture corpus:

- **Determinism:** `graph.json` is byte-identical across rebuilds (enforced in CI).
- **Provenance integrity:** 100% of non-`GENERATED` edges re-hash against source.
- Node/edge counts, degree distribution, modularity, component count, orphan rate
  (populated as L1+ land).

## Extrinsic benchmarks (Phase 4)

Planned, each reported with paired token-cost and latency:

| Benchmark | Status |
| --- | --- |
| LoCoMo | planned (Phase 4) |
| LongMemEval-S | planned (Phase 4) |
| MuSiQue / 2WikiMultihopQA / HotpotQA | stretch |
| BEAM | stretch (honest low number on hard inputs) |

## Ablations (Phase 4+)

structural-only vs. +encoder IE vs. +coref vs. +ER vs. +LLM · PPR on/off ·
reranker on/off · chunk-size sweep · schema-free vs. schema-guided.
