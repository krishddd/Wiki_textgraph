"""TextGraph command-line entry point.

Phase 1 commands:
  * ``textgraph version`` — print the version.
  * ``textgraph build <path> [-o DIR]`` — run L0+L1 and write the textgraph-out/
    artifact directory (graph.json, GRAPH_REPORT.md, graph.html, schema.yaml,
    manifest.json). ``--json-only PATH`` writes just the byte-stable graph.json.

The human CLI and the (future) MCP tool surface are built off the same underlying
result objects, formatted two ways — never two drifting code paths (§6.4).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textgraph import __version__
from textgraph.l5_entity_resolution import build_records, render_audit, run_er
from textgraph.l8_retrieval import QueryEngine
from textgraph.l9_artifacts import write_artifacts
from textgraph.pipeline import build, build_graph_bytes


def _cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _engine(path: Path) -> QueryEngine:
    result = build(path)
    return QueryEngine(result.nodes, result.edges)


def _fmt_citation(cit: dict[str, object]) -> str:
    return f"[{cit['doc_id']}:{cit['start']}-{cit['end']}]"


def _cmd_query(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).search(args.query, k=args.k).to_dict()
    print(f"search: {res['query']}  (routing: {res['routing']})")
    for i, hit in enumerate(res["hits"], 1):
        cites = " ".join(_fmt_citation(c) for c in hit["citations"])
        print(f"  {i}. [{hit['kind']}] {hit['name']}  (score {hit['score']})")
        if hit["snippet"]:
            print(f"      {hit['snippet'][:160]}")
        if cites:
            print(f"      {cites}")
    if res["truncated"]:
        print("  ... (truncated to token budget)")
    return 0


def _cmd_path(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).path(args.source, args.target, k=args.k).to_dict()
    if not res["paths"]:
        print(f"no path found from {res['source']} to {res['target']}")
        return 0
    for i, p in enumerate(res["paths"], 1):
        print(f"path {i} (likelihood {p['likelihood']}): " + " -> ".join(p["nodes"]))
        for step in p["steps"]:
            cites = " ".join(_fmt_citation(c) for c in step["citations"])
            print(
                f"  {step['subject']} -{step['predicate']}-> {step['object']}"
                f"  [{step['tag']}] {cites}"
            )
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).why(args.node).to_dict()
    print(f"why: {res['name']}")
    for c in res["claims"]:
        cites = " ".join(_fmt_citation(x) for x in c["citations"])
        neg = " (negated)" if c["polarity"] == "neg" else ""
        if c["t_valid"] and c.get("t_invalid"):
            when = f"  valid=[{c['t_valid']}, {c['t_invalid']}) SUPERSEDED"
        elif c["t_valid"]:
            when = f"  valid=[{c['t_valid']}, now)"
        else:
            when = ""
        print(
            f"  {c['subject']} -{c['predicate']}-> {c['object']}{neg}"
            f"  [{c['tag']} {c['confidence']}]{when} {cites}"
        )
    if res["rationale"]:
        print("rationale:")
        for r in res["rationale"]:
            print(f"  - {r}")
    return 0


def _cmd_er_audit(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    result = build(root)
    records = build_records(result.nodes, result.edges)
    er = run_er(records)
    report = render_audit(er, records)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(report)
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2

    if args.json_only:
        data = build_graph_bytes(root)
        out = Path(args.json_only)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        print(f"wrote {out} ({len(data)} bytes)")
        return 0

    result = build(root)
    paths = write_artifacts(
        args.output,
        config_hash=result.config_hash,
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
        timings_ms=result.timings_ms,
        ie_stats=result.ie_stats,
        er_stats=result.er_stats,
        graph_stats=result.graph_stats,
    )
    ie = result.ie_stats
    er = result.er_stats
    gs = result.graph_stats
    print(
        f"built graph: {len(result.results)} docs, {len(result.nodes)} nodes, "
        f"{len(result.edges)} edges "
        f"({ie.get('entities', 0)} entities, {ie.get('relations', 0)} relations, "
        f"{er.get('canonical_entities', 0)} canonical merges, "
        f"{gs.get('claims', 0)} claims, {gs.get('communities', 0)} communities, "
        f"{gs.get('chunks', 0)} chunks)"
    )
    print(f"  {paths.graph_json}")
    print(f"  {paths.report}")
    print(f"  {paths.graph_html}")
    for warning in result.skipped:
        print(f"  skipped {warning}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="textgraph", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_version = sub.add_parser("version", help="print the TextGraph version")
    p_version.set_defaults(func=_cmd_version)

    p_build = sub.add_parser("build", help="build a knowledge graph from a corpus path")
    p_build.add_argument("path", help="file or directory to ingest")
    p_build.add_argument(
        "-o",
        "--output",
        default="textgraph-out",
        help="artifact directory (default: textgraph-out)",
    )
    p_build.add_argument(
        "--json-only", metavar="PATH", help="write only graph.json to PATH and exit"
    )
    p_build.set_defaults(func=_cmd_build)

    p_er = sub.add_parser("er", help="entity-resolution utilities")
    er_sub = p_er.add_subparsers(dest="er_command", required=True)
    p_audit = er_sub.add_parser("audit", help="audit proposed SAME_AS merges for review")
    p_audit.add_argument("path", help="corpus path to resolve")
    p_audit.add_argument("-o", "--output", help="write the audit markdown to this path")
    p_audit.set_defaults(func=_cmd_er_audit)

    p_query = sub.add_parser("query", help="hybrid search over a corpus (BM25 + graph PPR)")
    p_query.add_argument("path", help="corpus path to build and query")
    p_query.add_argument("query", help="natural-language query")
    p_query.add_argument("-k", type=int, default=5, help="number of hits (default 5)")
    p_query.set_defaults(func=_cmd_query)

    p_path = sub.add_parser("path", help="maximum-likelihood path(s) between two entities")
    p_path.add_argument("path", help="corpus path to build")
    p_path.add_argument("source", help="source entity (id or name)")
    p_path.add_argument("target", help="target entity (id or name)")
    p_path.add_argument("-k", type=int, default=1, help="number of paths (default 1)")
    p_path.set_defaults(func=_cmd_path)

    p_explain = sub.add_parser("explain", help="cited claims explaining an entity")
    p_explain.add_argument("path", help="corpus path to build")
    p_explain.add_argument("node", help="entity to explain (id or name)")
    p_explain.set_defaults(func=_cmd_explain)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
