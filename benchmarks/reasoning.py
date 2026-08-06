"""Graph-of-Thoughts benchmark — adaptive cost vs the static-topology baseline (Phase 10).

Phase 10 DoD: "every reasoning step cites real graph spans; adaptive cost < static-topology
baseline, shown empirically." This harness runs a set of fixture questions through the
reasoner twice — ``adaptive`` (complexity-gated) and ``static`` (full topology) — and
reports, per query, the tool-call cost of each and whether every thought stayed grounded.
Cost is the number of graph tool calls (search/neighbors/path/why/gql) the reasoner made:
a deterministic, machine-independent count (no wall-clock), so the comparison is stable.

Usage:
    python -m benchmarks.reasoning          # print the report
    python -m benchmarks.reasoning --write   # also append the block to BENCHMARKS.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textgraph.got import GraphOfThoughts
from textgraph.pipeline import build

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "corpora" / "docs"
QUERIES = [
    "who is John Doe",
    "which bank was involved",
    "how is Acme Corp connected to Delta Trust",
    "what is the link between Beta Ltd and Gamma Holdings",
    "who controls Gamma Holdings",
]


def run() -> str:
    r = build(FIXTURE)
    got = GraphOfThoughts(r.nodes, r.edges)
    rows: list[tuple[str, int, int, int, bool]] = []
    for q in QUERIES:
        a = got.reason(q, mode="adaptive")
        s = got.reason(q, mode="static")
        rows.append((q, a.complexity, a.tool_calls, s.tool_calls, a.grounded and s.grounded))

    adaptive_total = sum(r[2] for r in rows)
    static_total = sum(r[3] for r in rows)
    saving = (1.0 - adaptive_total / static_total) * 100 if static_total else 0.0
    all_grounded = all(r[4] for r in rows)
    all_cheaper = all(r[2] <= r[3] for r in rows)

    lines = [
        "## Graph-of-Thoughts (Phase 10) - adaptive vs static reasoning cost",
        "",
        f"Fixture: `tests/fixtures/corpora/docs`, {len(QUERIES)} questions. Cost = graph "
        "tool calls (search/neighbors/path/why/gql); deterministic, machine-independent.",
        "",
        "| Question | complexity | adaptive calls | static calls | grounded |",
        "|---|---|---|---|---|",
    ]
    for q, cx, ac, sc, g in rows:
        lines.append(f"| {q} | {cx} | {ac} | {sc} | {g} |")
    lines += [
        "",
        f"- **Total cost: adaptive {adaptive_total} vs static {static_total} tool calls "
        f"-> {saving:.0f}% cheaper.** Adaptive is never more expensive than static: "
        f"**{all_cheaper}**.",
        f"- **Every reasoning step cites real graph spans (ESCARGOT): {all_grounded}.**",
        "- Adaptive spends where difficulty is: a single-entity question runs a cheap linear "
        "chain, while a connection question spawns the Aggregation/Refinement branches.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Graph-of-Thoughts adaptive-vs-static benchmark")
    parser.add_argument("--write", action="store_true", help="append the block to BENCHMARKS.md")
    args = parser.parse_args(argv)
    report = run()
    print(report)
    if args.write:
        path = REPO / "BENCHMARKS.md"
        prior = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(prior.rstrip() + "\n\n" + report, encoding="utf-8")
        print(f"(appended to {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
