"""``textgraph console`` — a local, zero-dependency web UI over the QueryEngine (G2).

A thin ``http.server`` wrapper around the pure :func:`textgraph.console.api.route`
function: it builds a :class:`QueryEngine` from a corpus (or a ``.duckdb`` snapshot),
binds to localhost, and serves the self-contained console page + JSON API. No external
frameworks; read-only; all the interesting logic is in :mod:`textgraph.console.api`,
which is unit-tested without a socket.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from textgraph.console.api import route
from textgraph.l8_retrieval.engine import QueryEngine


def build_engine(source: str | Path) -> QueryEngine:
    """Build a QueryEngine from a corpus directory or a persisted ``.duckdb`` file."""
    path = Path(source)
    if path.is_file() and path.suffix == ".duckdb":
        from textgraph.store.duckdb_store import load_graph

        nodes, edges = load_graph(path)
        return QueryEngine(nodes, edges)
    from textgraph.pipeline import build

    result = build(path)
    return QueryEngine(result.nodes, result.edges)


def _make_handler(engine: QueryEngine) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _respond(self, params: dict[str, str]) -> None:
            parsed = urlparse(self.path)
            merged = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            merged.update(params)
            status, content_type, body = route(engine, parsed.path, merged)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._respond({})

        def do_POST(self) -> None:
            # POST bodies carry long questions (the chat) — JSON or urlencoded, merged into
            # the request params so route() stays a pure function of (path, params).
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            params: dict[str, str] = {}
            if raw:
                ctype = self.headers.get("Content-Type", "")
                try:
                    if "application/json" in ctype:
                        params = {str(k): str(v) for k, v in json.loads(raw).items()}
                    else:
                        params = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
                except (ValueError, UnicodeDecodeError):
                    params = {}
            self._respond(params)

        def log_message(self, *args: object) -> None:
            pass  # keep the console quiet

    return Handler


def serve(
    engine: QueryEngine, *, host: str = "127.0.0.1", port: int = 8765
) -> None:  # pragma: no cover - binds a socket
    """Serve the console until interrupted (Ctrl-C)."""
    server = ThreadingHTTPServer((host, port), _make_handler(engine))
    print(f"TextGraph console: http://{host}:{port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
