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

from textgraph.core.config import Config
from textgraph.pipeline import build, build_graph

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "corpora" / "docs"


def _ablation(corpus: Path) -> dict[str, object]:
    """L1-only (structural spine) vs. +encoder IE — the Phase-2 ablation.

    Shows the node/edge/entity/relation delta the IE layer adds. Deterministic, so
    the numbers are reproducible and diffable across runs.
    """
    spine = build(corpus, config=Config(extract_ie=False))
    full = build(corpus, config=Config(extract_ie=True))
    return {
        "L1_only": {"nodes": len(spine.nodes), "edges": len(spine.edges)},
        "plus_encoder_ie": {
            "nodes": len(full.nodes),
            "edges": len(full.edges),
            "entities": full.ie_stats.get("entities", 0),
            "relations": full.ie_stats.get("relations", 0),
            "coref_resolved": full.ie_stats.get("pronouns_resolved", 0),
            "coref_total": full.ie_stats.get("pronouns_total", 0),
            "canonical_merges": full.er_stats.get("canonical_entities", 0),
            "same_as_edges": full.er_stats.get("same_as_edges", 0),
        },
        "delta": {
            "nodes": len(full.nodes) - len(spine.nodes),
            "edges": len(full.edges) - len(spine.edges),
        },
    }


def run(corpus: Path) -> dict[str, object]:
    graph = build_graph(corpus)
    return {
        "corpus": str(corpus.relative_to(ROOT)) if corpus.is_relative_to(ROOT) else str(corpus),
        "intrinsic": {
            "doc_count": graph["stats"]["doc_count"],
            "total_raw_bytes": graph["stats"]["total_raw_bytes"],
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
            "tag_counts": graph["stats"].get("tag_counts", {}),
            "config_hash": graph["config_hash"],
        },
        "ablation": _ablation(corpus),
        # Extrinsic (LoCoMo / LongMemEval-S) arrive in Phase 4.
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

    abl = result.get("ablation")
    if isinstance(abl, dict):
        spine = abl["L1_only"]
        full = abl["plus_encoder_ie"]
        delta = abl["delta"]
        lines += [
            "",
            "## Ablation: structural spine (L1) vs. + encoder IE (L2+L3)",
            "",
            "| configuration | nodes | edges | entities | relations |",
            "| --- | --- | --- | --- | --- |",
            f"| L1 only | {spine['nodes']} | {spine['edges']} | 0 | 0 |",
            f"| + encoder IE | {full['nodes']} | {full['edges']} | "
            f"{full['entities']} | {full['relations']} |",
            f"| **delta** | +{delta['nodes']} | +{delta['edges']} | "
            f"+{full['entities']} | +{full['relations']} |",
            "",
            f"Coreference-lite resolved {full['coref_resolved']}/{full['coref_total']} pronouns; "
            f"entity resolution merged aliases into {full['canonical_merges']} canonical "
            f"entities via {full['same_as_edges']} SAME_AS links.",
        ]

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
