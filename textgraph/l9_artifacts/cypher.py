"""Cypher (openCypher) export (L9) — load the graph into Neo4j / Memgraph / AGE, dep-free.

Emits a deterministic openCypher script that recreates the whole graph in any Bolt /
openCypher database (Neo4j, Memgraph, FalkorDB, Apache AGE, Amazon Neptune). This is exactly
the shape ``docs/plans/neo4j-backend.md`` calls for: the database is a **materialization
target** for the already-built ``graph.json`` — the build stays local, deterministic, and
DB-free, and every node/edge carries its ``[doc:start-end]`` citation + ``hash`` as
properties, so provenance re-verification (G3) works over the graph store too.

Mapping (all idempotent, so re-running the script is safe):

* node -> ``MERGE (n:Label1:Label2 {id:"…"}) SET n.name="…", n.<prop>=…``
* edge -> ``MATCH (a {id:"…"}),(b {id:"…"}) MERGE (a)-[r:PREDICATE]->(b)
  SET r.confidence=…, r.tag="…", r.predicate="<original>", r.doc="…", r.start=…, r.end=…``

Deterministic: nodes sorted by id, edges by edge_id, property keys sorted, values escaped, so
the script is byte-stable (G1) like ``graph.json``. Pure string emission — no driver.
"""

from __future__ import annotations

from textgraph.store.base import Edge, Node

_HEADER = (
    "// TextGraph openCypher export - load into Neo4j / Memgraph / AGE / Neptune.\n"
    "//   Neo4j:  cat graph.cypher | cypher-shell -u neo4j -p <pw>\n"
    "//   (or paste into the Neo4j Browser). MERGE keys on `id`; add an index for scale:\n"
    "//   CREATE INDEX tg_id IF NOT EXISTS FOR (n:Entity) ON (n.id);\n"
    "// Every relationship keeps its ConfidenceTag + [doc:start-end] byte citation.\n"
)
# Layout-only node properties the graph console adds; not worth materializing in a DB.
_SKIP_PROPS = frozenset({"x", "y"})


def _ident(text: str, *, upper: bool = False) -> str:
    """Sanitise a label / relationship type to a safe Cypher identifier.

    Keeps letters, digits and underscores; anything else becomes ``_``; a leading non-letter
    is prefixed so the token is always a valid identifier. Relationship types are upper-cased.
    """
    out = []
    for ch in text:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    ident = "".join(out) or "_"
    if not (ident[0].isalpha() or ident[0] == "_"):
        ident = "_" + ident
    return ident.upper() if upper else ident


def _lit(value: object) -> str:
    """Render a scalar as a Cypher literal (quoted+escaped string, or bare number/bool)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{s}"'


def _scalar_props(props: dict[str, object]) -> list[tuple[str, str]]:
    """Sorted ``(key, literal)`` pairs for the scalar, non-layout properties."""
    out: list[tuple[str, str]] = []
    for key in sorted(props):
        if key in _SKIP_PROPS or key == "id":
            continue
        val = props[key]
        if isinstance(val, (str, int, float, bool)):
            out.append((_ident(key), _lit(val)))
    return out


def export_cypher_bytes(nodes: list[Node], edges: list[Edge]) -> bytes:
    """Serialise ``(nodes, edges)`` to a deterministic openCypher load script (UTF-8 bytes)."""
    lines: list[str] = [_HEADER, "// --- nodes ---"]
    for n in sorted(nodes, key=lambda x: x.node_id):
        labels = "".join(f":{_ident(lbl)}" for lbl in n.labels) or ":Node"
        stmt = f"MERGE (n{labels} {{id:{_lit(n.node_id)}}})"
        sets = _scalar_props(n.properties)
        if sets:
            stmt += " SET " + ", ".join(f"n.{k}={v}" for k, v in sets)
        lines.append(stmt + ";")

    lines.append("// --- relationships ---")
    for e in sorted(edges, key=lambda x: x.edge_id):
        rel = _ident(e.predicate, upper=True)
        sets = [
            ("predicate", _lit(e.predicate)),
            ("tag", _lit(str(e.tag))),
            ("confidence", _lit(round(e.confidence, 4))),
            ("evidence_count", _lit(e.evidence_count)),
        ]
        if e.source_spans:
            sp = e.source_spans[0]
            sets += [("doc", _lit(sp.doc_id)), ("start", _lit(sp.start)), ("end", _lit(sp.end))]
            if getattr(sp, "hash", None):
                sets.append(("hash", _lit(sp.hash)))
            if sp.page:
                sets.append(("page", _lit(sp.page)))
            if sp.bbox is not None:
                sets.append(("bbox", _lit(",".join(repr(c) for c in sp.bbox))))
        set_clause = ", ".join(f"r.{k}={v}" for k, v in sets)
        lines.append(
            f"MATCH (a {{id:{_lit(e.subject)}}}), (b {{id:{_lit(e.object)}}}) "
            f"MERGE (a)-[r:{rel}]->(b) SET {set_clause};"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")
