"""PROV-O export (L9) — decision provenance as an interoperable audit trail.

Maps TextGraph's ``Decision`` layer onto the W3C PROV data model so an auditor (or any
PROV-aware tool) can reconstruct *inputs -> decision -> downstream effects*:

* ``Decision``            -> ``prov:Activity``
* source ``Document``     -> ``prov:Entity`` (what the activity ``prov:used``)
* the derived-from ``Rationale`` span -> carried as ``textgraph:sourceSpan`` on the
  activity (byte-range citation, re-verifiable — G3)
* the TextGraph extractor -> ``prov:SoftwareAgent`` (``prov:wasAssociatedWith``)
* ``CAUSED`` / ``INFLUENCED`` / ``PRECEDENT_FOR`` -> ``prov:wasInformedBy`` between
  activities (the effect ``wasInformedBy`` its cause)

Emitted as JSON-LD with a compact ``@context`` — plain JSON, no RDF library, and byte-
stable via the same canonical dumper as ``graph.json`` (G1). Domain specifics live under
a ``textgraph:`` extension namespace rather than inventing new top-level PROV classes, the
same subclassing discipline GDPRov follows.
"""

from __future__ import annotations

from typing import Any

from textgraph import __version__
from textgraph.core.canonical_json import canonical_dump_bytes
from textgraph.store.base import Edge, Node

PROV = "http://www.w3.org/ns/prov#"
TEXTGRAPH_NS = "https://textgraph.dev/ns#"
_AGENT_ID = "textgraph:extractor"
_CAUSAL = {"CAUSED", "INFLUENCED", "PRECEDENT_FOR"}


def _context() -> dict[str, Any]:
    return {
        "prov": PROV,
        "textgraph": TEXTGRAPH_NS,
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "used": {"@id": "prov:used", "@type": "@id"},
        "wasAssociatedWith": {"@id": "prov:wasAssociatedWith", "@type": "@id"},
        "wasInformedBy": {"@id": "prov:wasInformedBy", "@type": "@id"},
    }


def build_prov_document(nodes: list[Node], edges: list[Edge]) -> dict[str, Any]:
    """Assemble the PROV-O JSON-LD document (a plain dict, ready to serialize)."""
    decisions = {n.node_id: n for n in nodes if "Decision" in n.labels}

    # The span each Decision was derived from (its byte-range citation) + the doc it used.
    span_of: dict[str, Any] = {}
    for e in edges:
        if e.predicate == "DERIVED_FROM" and e.subject in decisions and e.source_spans:
            s = e.source_spans[0]
            span_of.setdefault(
                e.subject, {"doc_id": s.doc_id, "start": s.start, "end": s.end, "hash": s.hash}
            )

    entities: dict[str, dict[str, Any]] = {}
    activities: dict[str, dict[str, Any]] = {}

    def doc_entity_id(doc_id: str) -> str:
        eid = f"textgraph:document/{doc_id}"
        entities.setdefault(eid, {"@id": eid, "@type": "prov:Entity", "rdfs:label": doc_id})
        return eid

    for did, dnode in decisions.items():
        span = span_of.get(did)
        doc_id = str(dnode.properties.get("doc_id", "")) or (span["doc_id"] if span else "")
        activity: dict[str, Any] = {
            "@id": f"textgraph:{did}",
            "@type": "prov:Activity",
            "rdfs:label": str(dnode.properties.get("name", "")),
            "textgraph:category": str(dnode.properties.get("category", "")),
            "wasAssociatedWith": _AGENT_ID,
        }
        if doc_id:
            activity["used"] = [doc_entity_id(doc_id)]
        if span is not None:
            activity["textgraph:sourceSpan"] = span
        activities[did] = activity

    # Causal edges: the effect (object) wasInformedBy its cause (subject).
    for e in edges:
        if e.predicate in _CAUSAL and e.subject in activities and e.object in activities:
            effect = activities[e.object]
            informants = effect.setdefault("wasInformedBy", [])
            informant_id = f"textgraph:{e.subject}"
            if informant_id not in informants:
                informants.append(informant_id)
            # Record which causal flavor, since PROV collapses all three to wasInformedBy.
            flavors = effect.setdefault("textgraph:causedBy", [])
            flavors.append({"activity": informant_id, "relation": e.predicate})

    agent = {
        "@id": _AGENT_ID,
        "@type": ["prov:SoftwareAgent", "prov:Agent"],
        "rdfs:label": "TextGraph deterministic extractor",
        "textgraph:toolVersion": __version__,
    }

    # Sort every collection by a stable key so the document is byte-identical run to run.
    for act in activities.values():
        if "wasInformedBy" in act:
            act["wasInformedBy"] = sorted(act["wasInformedBy"])
        if "textgraph:causedBy" in act:
            act["textgraph:causedBy"] = sorted(
                act["textgraph:causedBy"], key=lambda c: (c["activity"], c["relation"])
            )
    graph = sorted([agent, *entities.values(), *activities.values()], key=lambda o: str(o["@id"]))
    return {"@context": _context(), "@graph": graph}


def export_prov_bytes(nodes: list[Node], edges: list[Edge]) -> bytes:
    """Serialize the PROV-O JSON-LD document to canonical, byte-stable UTF-8 bytes."""
    return canonical_dump_bytes(build_prov_document(nodes, edges))
