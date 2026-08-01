"""Benchmark runner entry point (`python -m benchmarks.run`).

Phase 0 emits intrinsic graph-health metrics on the fixture corpus and writes a
diffable Markdown report. Extrinsic accuracy benchmarks (paired with tokens/query
and p50/p95 latency, per Section 8) are added in Phase 4 — a number is never
reported here without its cost.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from textgraph.pipeline import build_graph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "corpus_docs"


def run(corpus: Path) -> dict[str, object]:
    graph = build_graph(corpus)
    return {
        "corpus": str(corpus.relative_to(ROOT)) if corpus.is_relative_to(ROOT) else str(corpus),
        "intrinsic": {
            "doc_count": graph["stats"]["doc_count"],
            "total_raw_bytes": graph["stats"]["total_raw_bytes"],
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "config_hash": graph["config_hash"],
        },
        # Extrinsic (LoCoMo / LongMemEval-S) + ablations arrive in Phase 4.
        "extrinsic": {},
    }


def render_report(result: dict[str, object]) -> str:
    intr = result["intrinsic"]
    assert isinstance(intr, dict)
    lines = [
        "# TextGraph Benchmark Report",
        "",
        f"Corpus: `{result['corpus']}`",
        "",
        "## Intrinsic (graph health)",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    for key in sorted(intr):
        lines.append(f"| {key} | {intr[key]} |")
    lines += [
        "",
        "## Extrinsic",
        "",
        "_Extrinsic accuracy benchmarks (paired with tokens/query and latency) land in Phase 4._",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmarks.run")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--report", default=None, help="write a Markdown report to this path")
    parser.add_argument("--json", action="store_true", help="print raw JSON to stdout")
    args = parser.parse_args(argv)

    result = run(Path(args.corpus))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_report(result))
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
