"""``textgraph console`` — a local, zero-dependency web UI over the QueryEngine (G2).

A thin ``http.server`` wrapper around the pure :func:`textgraph.console.api.route`
function: it builds a :class:`QueryEngine` from a corpus (or a ``.duckdb`` snapshot),
binds to localhost, and serves the self-contained console page + JSON API. No external
frameworks; read-only by default. The only mutation is optional file ingestion, wired only
when ``allow_ingest`` is set (``--allow-ingest``): a ``POST /api/ingest`` writes the upload
into the corpus dir and hot-swaps a freshly-rebuilt engine. All the read logic lives in
:mod:`textgraph.console.api` and the ingest core in :mod:`textgraph.console.ingest`, both
unit-tested without a socket.
"""

from __future__ import annotations

import json
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from textgraph.console.api import route
from textgraph.l8_retrieval.engine import QueryEngine


def build_engine(source: str | Path) -> QueryEngine:
    """Build a QueryEngine from a corpus dir, a ``.duckdb`` file, or a built ``graph.json``.

    Passing a ``graph.json`` (or a build-output directory containing one) serves the
    *already-built* graph without re-running the pipeline — so an LLM-enriched build
    (``build --llm-extract``) shows all its relations in the UI, instead of the console
    silently rebuilding with the deterministic default.
    """
    path = Path(source)
    if path.is_dir() and (path / "graph.json").is_file():
        path = path / "graph.json"  # a build-output dir -> serve its graph.json
    if path.is_file() and path.suffix == ".json":
        from textgraph.l9_artifacts.graph_json import load_graph_json

        nodes, edges = load_graph_json(path)
        return QueryEngine(nodes, edges)
    if path.is_file() and path.suffix == ".duckdb":
        from textgraph.store.duckdb_store import load_graph

        nodes, edges = load_graph(path)
        return QueryEngine(nodes, edges)
    from textgraph.pipeline import build

    result = build(path)
    return QueryEngine(result.nodes, result.edges)


@dataclass
class _State:
    """Server-held mutable state: the current engine + ingestion/auth config.

    Concurrency model: ``ThreadingHTTPServer`` serves each request on its own thread. Reads
    are safe — swapping ``engine`` is a single atomic reference assignment (GIL), so a reader
    sees either the old or the new engine, never a torn one. The only mutation, ingestion, is
    serialized by ``ingest_lock`` so two concurrent uploads can't race the rebuild/swap.
    """

    engine: QueryEngine
    source: str | None
    allow_ingest: bool
    cache_dir: str | None
    token: str | None = None
    ingest_lock: threading.Lock = field(default_factory=threading.Lock)


def _make_handler(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, ctype: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            self._send(status, "application/json", json.dumps(payload, ensure_ascii=False).encode())

        def _route(self, params: dict[str, str]) -> None:
            parsed = urlparse(self.path)
            merged = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            merged.update(params)
            status, ctype, body = route(state.engine, parsed.path, merged)
            self._send(status, ctype, body)

        def _authed(self) -> bool:
            # Optional bearer-token auth (only enforced when --token was given). The page
            # itself is always served; only /api/* requires the token.
            if not state.token or not urlparse(self.path).path.startswith("/api/"):
                return True
            header = self.headers.get("Authorization", "")
            supplied = header[7:] if header.startswith("Bearer ") else ""
            if not supplied:
                supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            if supplied == state.token:
                return True
            self._json(401, {"error": "unauthorized"})
            return False

        def do_GET(self) -> None:
            if not self._authed():
                return
            path = urlparse(self.path).path
            # /api/config reports server-level flags the read-only route() can't know.
            if path == "/api/config":
                self._json(200, {"ingest": state.allow_ingest, "auth": bool(state.token)})
                return
            if path == "/api/export":
                self._export()
                return
            self._route({})

        def _export(self) -> None:
            # Save a graph.json snapshot of the CURRENT graph (reflects any in-UI ingest).
            # A corpus-dir console rebuilds from source for a complete artifact (with docs);
            # a .duckdb / no-source console serializes the live engine's nodes + edges.
            if state.source and Path(state.source).is_dir():
                from textgraph.pipeline import build_graph_bytes

                body = build_graph_bytes(Path(state.source))
            else:
                from textgraph.console.api import export_graph_bytes

                body = export_graph_bytes(state.engine)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", 'attachment; filename="graph.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if not self._authed():
                return
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            if parsed.path == "/api/ingest":
                self._ingest(raw)
                return
            # Other POSTs (the chat) carry JSON/urlencoded params merged into route().
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
            self._route(params)

        def _ingest(self, raw: bytes) -> None:
            if not state.allow_ingest or not state.source:
                self._json(
                    403, {"ok": False, "error": "ingestion disabled (start with --allow-ingest)"}
                )
                return
            from textgraph.console.chat import forget
            from textgraph.console.ingest import ingest_files, parse_multipart

            uploads = parse_multipart(self.headers.get("Content-Type", ""), raw)
            if not uploads:
                self._json(400, {"ok": False, "error": "no files in request"})
                return
            # Serialize ingests so two concurrent uploads can't race the rebuild + swap.
            with state.ingest_lock:
                before = {state.engine._name(n) for n in state.engine._entity_ids}
                res = ingest_files(state.source, uploads, cache_dir=state.cache_dir)
                if not res.ok:
                    self._json(
                        400, {"ok": False, "error": "no accepted files", "rejected": res.rejected}
                    )
                    return
                old = state.engine
                state.engine = QueryEngine(res.nodes, res.edges)
                forget(old)  # the swapped-out engine's cached reasoner is now stale
                after = {state.engine._name(n) for n in state.engine._entity_ids}
            self._json(
                200,
                {
                    "ok": True,
                    "written": res.written,
                    "rejected": res.rejected,
                    "added_entities": sorted(after - before),
                },
            )

        def log_message(self, *args: object) -> None:
            pass  # keep the console quiet

    return Handler


def serve(
    engine: QueryEngine,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    source: str | Path | None = None,
    allow_ingest: bool = False,
    token: str | None = None,
) -> None:  # pragma: no cover - binds a socket
    """Serve the console until interrupted (Ctrl-C).

    Pass ``source`` + ``allow_ingest=True`` to enable file-attach ingestion; ``token`` turns
    on bearer-token auth on ``/api/*`` (recommended before binding a non-localhost host).
    """
    cache_dir = tempfile.mkdtemp(prefix="tg-console-") if (allow_ingest and source) else None
    state = _State(engine, str(source) if source else None, allow_ingest, cache_dir, token)
    server = ThreadingHTTPServer((host, port), _make_handler(state))
    extra = ("  · ingest ON" if state.allow_ingest else "") + ("  · auth ON" if token else "")
    print(f"TextGraph console: http://{host}:{port}  (Ctrl-C to stop){extra}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
