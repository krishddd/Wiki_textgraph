"""Ontology export (L9) — OWL + SHACL derived from the graph, dependency-free.

The graph's own shape *is* an ontology: node labels are classes, edge predicates are object
properties, scalar property keys are datatype properties. This module reads that shape back
out as two standard artifacts — an **OWL** vocabulary and a **SHACL** shapes graph — so the
graph can be validated and reasoned over in any semantic-web toolchain (Jena, TopBraid,
pySHACL, …). Closes the "formal ontology / validation" gap without an RDF dependency.

Both are emitted as deterministic Turtle (sorted, content-stable, G1). Domain/range and
SHACL constraints are *induced* from what actually occurs in the graph — an honest schema
of the data, not a hand-waved one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textgraph.l9_artifacts.rdf import _PREFIXES, _iri, _lit
from textgraph.store.base import Edge, Node

_OWL = "http://www.w3.org/2002/07/owl#"
_SH = "http://www.w3.org/ns/shacl#"
_SHAPE_NS = f"{_PREFIXES['tg']}shape/"
_PLUMBING = frozenset({"SUBJECT_OF", "HAS_OBJECT", "HAS_CHUNK", "CONTAINS", "MENTIONS"})


@dataclass(frozen=True)
class _Schema:
    classes: list[str]
    predicates: list[str]
    prop_keys: list[str]
    domain: dict[str, set[str]] = field(default_factory=dict)  # predicate -> subject labels
    rng: dict[str, set[str]] = field(default_factory=dict)  # predicate -> object labels


def _schema(nodes: list[Node], edges: list[Edge]) -> _Schema:
    """Induce the schema: classes, predicates, property keys, and domain/range sets."""
    labels_of = {n.node_id: tuple(sorted(n.labels)) for n in nodes}
    classes: set[str] = {lbl for n in nodes for lbl in n.labels}
    prop_keys: set[str] = {
        k
        for n in nodes
        for k, v in n.properties.items()
        if k != "name" and isinstance(v, str | int | float | bool)
    }
    domain: dict[str, set[str]] = {}
    rng: dict[str, set[str]] = {}
    predicates: set[str] = set()
    for e in edges:
        if e.predicate in _PLUMBING:
            continue
        predicates.add(e.predicate)
        for lbl in labels_of.get(e.subject, ()):
            domain.setdefault(e.predicate, set()).add(lbl)
        for lbl in labels_of.get(e.object, ()):
            rng.setdefault(e.predicate, set()).add(lbl)
    return _Schema(
        classes=sorted(classes),
        predicates=sorted(predicates),
        prop_keys=sorted(prop_keys),
        domain=domain,
        rng=rng,
    )


def _header(extra: dict[str, str]) -> list[str]:
    prefixes = {**_PREFIXES, **extra}
    return [f"@prefix {p}: <{u}> ." for p, u in sorted(prefixes.items())] + [""]


def build_owl(nodes: list[Node], edges: list[Edge]) -> str:
    """Emit an OWL vocabulary (Turtle) of the graph's classes + properties."""
    s = _schema(nodes, edges)
    lines = _header({"owl": _OWL})
    for cls in s.classes:
        lines.append(f"{_iri('tgc', cls)} a owl:Class ;\n    rdfs:label {_lit(cls)} .")
    lines.append("")
    for pred in s.predicates:
        parts = [f"{_iri('tgr', pred)} a owl:ObjectProperty", f"rdfs:label {_lit(pred)}"]
        doms = sorted(s.domain.get(pred, set()))
        rngs = sorted(s.rng.get(pred, set()))
        if len(doms) == 1:
            parts.append(f"rdfs:domain {_iri('tgc', doms[0])}")
        if len(rngs) == 1:
            parts.append(f"rdfs:range {_iri('tgc', rngs[0])}")
        lines.append(" ;\n    ".join(parts) + " .")
    lines.append("")
    for key in s.prop_keys:
        lines.append(f"{_iri('tgo', key)} a owl:DatatypeProperty ;\n    rdfs:label {_lit(key)} .")
    return "\n".join(lines) + "\n"


def build_shacl(nodes: list[Node], edges: list[Edge]) -> str:
    """Emit a SHACL shapes graph (Turtle) inducing per-class constraints from the data."""
    s = _schema(nodes, edges)
    lines = _header({"sh": _SH, "tgs": _SHAPE_NS})
    # Which relation predicates leave each class (for per-class property shapes).
    out_preds: dict[str, set[str]] = {}
    for pred in s.predicates:
        for dom in s.domain.get(pred, set()):
            out_preds.setdefault(dom, set()).add(pred)

    for cls in s.classes:
        shape = f"<{_SHAPE_NS}{cls}>"
        block = [
            f"{shape} a sh:NodeShape",
            f"sh:targetClass {_iri('tgc', cls)}",
            "sh:property [ sh:path rdfs:label ; sh:datatype xsd:string ; sh:minCount 1 ]",
        ]
        for pred in sorted(out_preds.get(cls, set())):
            rngs = sorted(s.rng.get(pred, set()))
            constraint = f"sh:path {_iri('tgr', pred)}"
            if len(rngs) == 1:
                constraint += f" ; sh:class {_iri('tgc', rngs[0])}"
            block.append(f"sh:property [ {constraint} ]")
        lines.append(" ;\n    ".join(block) + " .")
    return "\n".join(lines) + "\n"


def export_owl_bytes(nodes: list[Node], edges: list[Edge]) -> bytes:
    return build_owl(nodes, edges).encode("utf-8")


def export_shacl_bytes(nodes: list[Node], edges: list[Edge]) -> bytes:
    return build_shacl(nodes, edges).encode("utf-8")
