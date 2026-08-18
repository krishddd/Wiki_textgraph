"""SKOS export (L9) — the graph's communities as a concept scheme, dependency-free.

SKOS (Simple Knowledge Organization System) is the W3C vocabulary for thesauri and controlled
vocabularies. TextGraph's community structure *is* a lightweight knowledge organization: the L7
communities are topics, and the entities are the terms under them. This module reads that back
out as a standard ``skos:ConceptScheme`` so the graph's organization drops straight into any
SKOS toolchain (SKOSMOS, PoolParty, VocBench, rdflib).

The mapping, all induced from the built graph:

* one ``skos:ConceptScheme`` for the corpus;
* each **community** → a ``skos:Concept`` (a topic), ``skos:prefLabel`` = its c-TF-IDF label,
  ``skos:topConceptOf`` the scheme;
* each **entity** → a ``skos:Concept`` with ``skos:prefLabel`` = its name and ``skos:broader``
  its community (the community gets the reciprocal ``skos:narrower``);
* **entity-resolution aliases** (``SAME_AS``) → ``skos:altLabel`` on the canonical concept — the
  resolved variants become the concept's alternative labels, exactly what altLabel is for.

Emitted as deterministic Turtle (sorted, content-stable, G1); query-time only, ``graph.json`` is
untouched. No RDF dependency.
"""

from __future__ import annotations

from textgraph.l9_artifacts.rdf import _PREFIXES, _iri, _lit
from textgraph.store.base import Edge, Node

_SKOS = "http://www.w3.org/2004/02/skos/core#"
_SCHEME = f"{_PREFIXES['tg']}scheme/corpus"


def _concept(kind: str, key: str) -> str:
    return _iri("tg", f"concept/{kind}/{key}")


def export_skos_bytes(nodes: list[Node], edges: list[Edge]) -> bytes:
    """Emit the graph's communities + entities as a SKOS concept scheme (deterministic Turtle)."""
    entities = [n for n in nodes if "Entity" in n.labels]
    names = {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}

    # Communities present, with their labels and members.
    comm_label: dict[int, str] = {}
    members: dict[int, list[str]] = {}
    for n in entities:
        cid = int(n.properties.get("community", -1))
        if cid < 0:
            continue
        comm_label.setdefault(cid, str(n.properties.get("community_label", f"community {cid}")))
        members.setdefault(cid, []).append(n.node_id)

    # SAME_AS aliases -> altLabels on the canonical entity concept.
    aliases: dict[str, list[str]] = {}
    for e in edges:
        if e.predicate == "SAME_AS" and e.subject in names and e.object in names:
            # convention: alias --SAME_AS--> canonical
            aliases.setdefault(e.object, []).append(names[e.subject])

    prefixes = dict(_PREFIXES)
    prefixes["skos"] = _SKOS
    lines: list[str] = [f"@prefix {p}: <{u}> ." for p, u in sorted(prefixes.items())]
    lines.append("")
    lines.append("# TextGraph SKOS export - communities as a concept scheme.")
    lines.append(f"<{_SCHEME}> a skos:ConceptScheme ;")
    lines.append('    skos:prefLabel "TextGraph corpus concepts" .')
    lines.append("")

    def _block(subject: str, pairs: list[tuple[str, str]]) -> None:
        # Emit `subject a skos:Concept ; p1 o1 ; ... ; pn on .` as clean, aligned Turtle.
        body = " ;\n".join(f"    {p} {o}" for p, o in pairs)
        lines.append(f"{subject} a skos:Concept ;\n{body} .")
        lines.append("")

    # Community concepts (topics) — top concepts of the scheme.
    lines.append("# --- communities (topics) ---")
    for cid in sorted(comm_label):
        pairs = [
            ("skos:prefLabel", _lit(comm_label[cid])),
            ("skos:topConceptOf", f"<{_SCHEME}>"),
            ("skos:inScheme", f"<{_SCHEME}>"),
        ]
        narrower = [_concept("entity", nid) for nid in sorted(members.get(cid, []))]
        if narrower:
            pairs.append(("skos:narrower", " , ".join(narrower)))
        _block(_concept("community", str(cid)), pairs)

    # Entity concepts (terms) — narrower under their community.
    lines.append("# --- entities (terms) ---")
    for n in sorted(entities, key=lambda x: x.node_id):
        pairs = [("skos:prefLabel", _lit(names[n.node_id]))]
        for alias in sorted(set(aliases.get(n.node_id, []))):
            if alias != names[n.node_id]:
                pairs.append(("skos:altLabel", _lit(alias)))
        cid = int(n.properties.get("community", -1))
        if cid in comm_label:
            pairs.append(("skos:broader", _concept("community", str(cid))))
        pairs.append(("skos:inScheme", f"<{_SCHEME}>"))
        _block(_concept("entity", n.node_id), pairs)
    return ("\n".join(lines)).encode("utf-8")
