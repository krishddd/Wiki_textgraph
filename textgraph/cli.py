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
from textgraph.l9_artifacts import write_artifacts
from textgraph.pipeline import build, build_graph_bytes


def _cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
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
    )
    print(
        f"built graph: {len(result.results)} docs, {len(result.nodes)} nodes, "
        f"{len(result.edges)} edges"
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
