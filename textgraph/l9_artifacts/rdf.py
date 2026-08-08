"""RDF export (L9) — the graph as a W3C RDF triple store, dependency-free.

Emits the whole graph as **Turtle** so it loads directly into Oxigraph, Apache Jena,
RDF4J, Blazegraph, or any SPARQL store — closing the "native RDF" gap with polyglot peers
without pulling an RDF library (pure string emission over stdlib).

Mapping:

* every node        -> a subject typed by each of its labels (``a tgc:<Label>``) with an
  ``rdfs:label`` and its scalar properties as ``tgo:<key>`` literals;
* every edge        -> a triple ``<subj> tgr:<PREDICATE> <obj>`` ;
* every cited edge  -> **also** a reified ``rdf:Statement`` (deterministic IRI) carrying the
  ``ConfidenceTag`` and the re-verifiable byte span (``tgo:sourceDoc/Start/End/Hash``), so
  provenance survives the round-trip into a triple store (G3).

Deterministic: IRIs are content-addressed, literals are escaped, and every block/line is
sorted, so the Turtle is byte-stable (G1) — like ``graph.json``.
"""

from __future__ import annotations

from urllib.parse import quote

from textgraph.core.content_address import hash_text
from textgraph.store.base import Edge, Node

BASE = "https://textgraph.dev"
_PREFIXES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "prov": "http://www.w3.org/ns/prov#",
    "tgo": f"{BASE}/ns#",  # ontology terms (property keys, provenance)
    "tgc": f"{BASE}/class/",  # node-label classes
    "tgr": f"{BASE}/rel/",  # relation predicates
    "tg": f"{BASE}/id/",  # node/statement resources
}
# Structural plumbing predicates are still emitted as triples, but only "real" relations
# get a reified provenance statement (keeps the output focused).
_PLUMBING = frozenset({"SUBJECT_OF", "HAS_OBJECT", "HAS_CHUNK", "CONTAINS"})


def _iri(prefix: str, local: str) -> str:
    """A full IRI ``<...>`` with the local part percent-encoded (always Turtle-valid)."""
    return f"<{_PREFIXES[prefix]}{quote(local, safe='')}>"


def _lit(value: str) -> str:
    """A Turtle string literal with the required escapes."""
    esc = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{esc}"'


def _obj_literal(value: object) -> str:
    """Render a scalar property value as a typed Turtle literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f'"{value}"^^xsd:integer'
    if isinstance(value, float):
        return f'"{value}"^^xsd:double'
    return _lit(str(value))


def build_turtle(nodes: list[Node], edges: list[Edge]) -> str:
    """Serialize ``(nodes, edges)`` to a deterministic Turtle document."""
    lines: list[str] = [f"@prefix {p}: <{u}> ." for p, u in sorted(_PREFIXES.items())]
    lines.append("")

    # -- nodes: type(s) + label + scalar properties ------------------------------
    for n in sorted(nodes, key=lambda n: n.node_id):
        subj = _iri("tg", n.node_id)
        preds: list[str] = []
        for label in sorted(n.labels):
            preds.append(f"a {_iri('tgc', label)}")
        name = n.properties.get("name")
        if isinstance(name, str) and name:
            preds.append(f"rdfs:label {_lit(name)}")
        for key in sorted(n.properties):
            if key == "name":
                continue
            val = n.properties[key]
            if isinstance(val, str | int | float | bool):
                preds.append(f"{_iri('tgo', key)} {_obj_literal(val)}")
        if preds:
            lines.append(f"{subj} " + " ;\n    ".join(preds) + " .")

    # -- edges: relation triples + reified provenance for cited, non-plumbing ones
    lines.append("")
    stmt_lines: list[str] = []
    for e in sorted(edges, key=lambda e: (e.subject, e.predicate, e.object)):
        s, p, o = _iri("tg", e.subject), _iri("tgr", e.predicate), _iri("tg", e.object)
        lines.append(f"{s} {p} {o} .")
        if e.predicate in _PLUMBING or not e.source_spans:
            continue
        span = e.source_spans[0]
        sid = _iri("tg", "stmt/" + hash_text(f"{e.subject}|{e.predicate}|{e.object}|{span.hash}"))
        stmt_lines.append(
            f"{sid} a rdf:Statement ;\n"
            f"    rdf:subject {s} ;\n"
            f"    rdf:predicate {p} ;\n"
            f"    rdf:object {o} ;\n"
            f"    tgo:confidenceTag {_lit(str(e.tag))} ;\n"
            f"    tgo:confidence {_obj_literal(round(e.confidence, 6))} ;\n"
            f"    prov:wasDerivedFrom {_lit(span.doc_id)} ;\n"
            f"    tgo:sourceStart {_obj_literal(span.start)} ;\n"
            f"    tgo:sourceEnd {_obj_literal(span.end)} ;\n"
            f"    tgo:sourceHash {_lit(span.hash)} ."
        )
    if stmt_lines:
        lines.append("")
        lines.append("# --- provenance (reified statements: cited, re-verifiable spans) ---")
        lines.extend(sorted(stmt_lines))
    return "\n".join(lines) + "\n"


def export_rdf_bytes(nodes: list[Node], edges: list[Edge]) -> bytes:
    """Serialize the graph to deterministic Turtle UTF-8 bytes."""
    return build_turtle(nodes, edges).encode("utf-8")
