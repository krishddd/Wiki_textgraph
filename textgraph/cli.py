"""TextGraph command-line entry point.

Build:
  * ``textgraph version`` — print the version.
  * ``textgraph build <path> [-o DIR]`` — run the full pipeline and write the
    textgraph-out/ artifacts. ``--json-only PATH`` writes just byte-stable graph.json.
  * ``textgraph er audit <path>`` — review proposed SAME_AS merges.

Query (all eight L8 tools, over the same ``QueryEngine`` the MCP server uses):
  * ``query`` (hybrid search), ``path`` (max-likelihood), ``explain`` (why),
    ``neighbors``, ``timeline``, ``contradictions``, ``communities``, ``stats``.

The human CLI and the MCP tool surface are built off the same underlying result
objects, formatted two ways — never two drifting code paths (§6.4).
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
    # A .duckdb path is a persisted graph — load it straight from disk (no rebuild).
    if path.is_file() and path.suffix == ".duckdb":
        from textgraph.store.duckdb_store import load_graph

        nodes, edges = load_graph(path)
        return QueryEngine(nodes, edges)
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


def _cmd_neighbors(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).neighbors(args.node, k=args.k).to_dict()
    print(f"neighbors of {res['name']}:")
    for n in res["neighbors"]:
        arrow = "->" if n["direction"] == "out" else "<-"
        cites = " ".join(_fmt_citation(c) for c in n["citations"])
        print(
            f"  {arrow} {n['predicate']} {n['other_name']}  [{n['tag']} {n['confidence']}] {cites}"
        )
    if res["truncated"]:
        print("  ... (truncated to token budget)")
    return 0


def _fmt_window(c: dict[str, object]) -> str:
    if c["t_valid"] and c.get("t_invalid"):
        return f"  valid=[{c['t_valid']}, {c['t_invalid']}) SUPERSEDED"
    if c["t_valid"]:
        return f"  valid=[{c['t_valid']}, now)"
    return ""


def _cmd_timeline(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).timeline(args.node).to_dict()
    print(f"timeline: {res['name']}")
    for c in res["events"]:
        neg = " (negated)" if c["polarity"] == "neg" else ""
        cites = " ".join(_fmt_citation(x) for x in c["citations"])
        print(f"  {c['subject']} -{c['predicate']}-> {c['object']}{neg}{_fmt_window(c)} {cites}")
    return 0


def _cmd_contradictions(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).contradictions().to_dict()
    if not res["pairs"]:
        print("no contradictions found")
        return 0
    print(f"contradictions: {len(res['pairs'])}")
    for p in res["pairs"]:
        a, b = p["claim_a"], p["claim_b"]
        print(f"  {a['subject']} -{a['predicate']}-> {a['object']}")
        print(f"    [{a['polarity']}]{_fmt_window(a)}  vs  [{b['polarity']}]{_fmt_window(b)}")
    return 0


def _cmd_communities(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).communities().to_dict()
    print(f"communities: {len(res['communities'])}")
    for c in res["communities"]:
        print(f"  #{c['community_id']} {c['label']} ({c['size']}): {', '.join(c['members'])}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    res = _engine(root).stats().to_dict()
    counts = res["counts"]
    print("stats:")
    for key in ("nodes", "edges", "entities", "chunks", "claims"):
        print(f"  {key}: {counts.get(key, 0)}")
    print("top entities (by PageRank):")
    for e in res["top_entities"]:
        print(f"  {e['name']}  pr={e['pagerank']}  [{e['community_label']}]")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    from textgraph.watch import watch

    def _report(result: object) -> None:
        r = result  # BuildResult
        print(
            f"rebuilt: {len(r.nodes)} nodes, {len(r.edges)} edges "  # type: ignore[attr-defined]
            f"-> {args.output}"
        )

    print(f"watching {root} (every {args.interval}s; Ctrl-C to stop)...")
    try:
        watch(root, args.output, interval=args.interval, on_build=_report)
    except KeyboardInterrupt:
        print("\nstopped.")
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

    from textgraph.core.config import Config

    config = Config(llm_enabled=True) if args.llm else None
    result = build(root, config=config)
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
        llm_enabled=result.config.llm_enabled,
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
    if args.store:
        from textgraph.store.duckdb_store import persist

        store_path = persist(args.store, result.nodes, result.edges)
        print(f"  {store_path} (persisted; query it directly without a rebuild)")
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
    p_build.add_argument(
        "--store",
        metavar="PATH.duckdb",
        help="also persist the graph to a DuckDB file (requires the [graph] extra)",
    )
    p_build.add_argument(
        "--llm",
        action="store_true",
        help="run the opt-in L4 LLM pass (GENERATED community summaries); reads "
        "API_KEY/MODEL_BASE_URL/MODEL_NAME from the environment",
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

    p_neigh = sub.add_parser("neighbors", help="1-hop typed neighbors of an entity")
    p_neigh.add_argument("path", help="corpus path to build")
    p_neigh.add_argument("node", help="entity (id or name)")
    p_neigh.add_argument("-k", type=int, default=20, help="max neighbors (default 20)")
    p_neigh.set_defaults(func=_cmd_neighbors)

    p_timeline = sub.add_parser("timeline", help="claims about an entity ordered by validity")
    p_timeline.add_argument("path", help="corpus path to build")
    p_timeline.add_argument("node", help="entity (id or name)")
    p_timeline.set_defaults(func=_cmd_timeline)

    p_contra = sub.add_parser("contradictions", help="opposite-polarity claim pairs, cited")
    p_contra.add_argument("path", help="corpus path to build")
    p_contra.set_defaults(func=_cmd_contradictions)

    p_comm = sub.add_parser("communities", help="detected communities with auto-labels")
    p_comm.add_argument("path", help="corpus path to build")
    p_comm.set_defaults(func=_cmd_communities)

    p_stats = sub.add_parser("stats", help="graph counts and most central entities")
    p_stats.add_argument("path", help="corpus path to build")
    p_stats.set_defaults(func=_cmd_stats)

    p_watch = sub.add_parser("watch", help="rebuild artifacts incrementally on corpus change")
    p_watch.add_argument("path", help="corpus directory to watch")
    p_watch.add_argument("-o", "--output", default="textgraph-out", help="artifact directory")
    p_watch.add_argument("--interval", type=float, default=2.0, help="poll interval seconds")
    p_watch.set_defaults(func=_cmd_watch)

    return parser


def main(argv: list[str] | None = None) -> int:
    from textgraph.l0_ingest.base import UnsupportedFormat

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
    except UnsupportedFormat as exc:
        # e.g. a .duckdb path or --store without the [graph] extra installed.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
