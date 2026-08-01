"""TextGraph command-line entry point.

Phase 0 ships two commands:
  * ``textgraph version`` — print the version.
  * ``textgraph build <path> [-o graph.json]`` — run the (trivial) pipeline and
    write a byte-stable ``graph.json``.

The human CLI and the (future) MCP tool surface are built off the same underlying
result objects, formatted two ways — never two drifting code paths (see §6.4).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textgraph import __version__
from textgraph.pipeline import build_graph_bytes


def _cmd_version(_: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"error: path does not exist: {root}", file=sys.stderr)
        return 2
    data = build_graph_bytes(root)
    out = Path(args.output)
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="textgraph", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_version = sub.add_parser("version", help="print the TextGraph version")
    p_version.set_defaults(func=_cmd_version)

    p_build = sub.add_parser("build", help="build a graph from a corpus path")
    p_build.add_argument("path", help="file or directory to ingest")
    p_build.add_argument(
        "-o", "--output", default="graph.json", help="output path (default: graph.json)"
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
