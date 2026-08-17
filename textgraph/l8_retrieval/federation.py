"""Cross-graph federation — query several case graphs at once (multi-case investigations).

The recurring question across a set of cases is *which entities span more than one case, and
what does each case say about them?* — the shared beneficial owner behind two frauds, the
account that surfaces in three investigations. Federation answers that **without merging the
corpora**: each ``graph.json`` stays its own reproducible artifact, and cross-case links are
discovered, not baked in.

The whole thing works because TextGraph ids are **content-addressed**: a canonical entity's
``node_id`` is a hash of its (type, normalized name), so *the same real-world entity gets the
same id in every corpus that names it*. Cross-case entity linking is therefore an id
intersection — the same insight that powers :mod:`textgraph.l9_artifacts.diff`. No fuzzy
matching, no id namespacing, no heuristics: deterministic and dependency-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from textgraph.store.base import Edge, Node

_PLUMBING = frozenset(
    {"MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS", "SAME_AS", "CONTRADICTS"}
)


@dataclass
class CaseGraph:
    """One named graph in the federation (a case)."""

    name: str
    nodes: list[Node]
    edges: list[Edge]

    def entities(self) -> dict[str, str]:
        """Entity ``node_id -> name`` for this case."""
        return {
            n.node_id: str(n.properties.get("name", n.node_id))
            for n in self.nodes
            if "Entity" in n.labels
        }

    def relations(self, node_id: str) -> list[dict[str, str]]:
        """Non-plumbing relations touching ``node_id``, with the other endpoint's name."""
        name = {n.node_id: str(n.properties.get("name", n.node_id)) for n in self.nodes}
        out: list[dict[str, str]] = []
        for e in self.edges:
            if e.predicate in _PLUMBING:
                continue
            if e.subject == node_id:
                out.append(
                    {
                        "predicate": e.predicate,
                        "direction": "out",
                        "other": name.get(e.object, e.object),
                    }
                )
            elif e.object == node_id:
                out.append(
                    {
                        "predicate": e.predicate,
                        "direction": "in",
                        "other": name.get(e.subject, e.subject),
                    }
                )
        return out


@dataclass
class SharedEntity:
    """An entity present in more than one case — a cross-case link."""

    node_id: str
    name: str
    cases: list[str]
    degree: dict[str, int] = field(default_factory=dict)  # case name -> relation degree

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "cases": self.cases,
            "case_count": len(self.cases),
            "degree": self.degree,
        }


def load_federation(paths: list[str | Path]) -> list[CaseGraph]:
    """Load several ``graph.json`` files (or dirs containing one) as named cases.

    A case's name is its file stem (or the directory name), so reports read naturally. Raises
    ``FileNotFoundError`` if a path has no graph.json.
    """
    from textgraph.l9_artifacts.graph_json import load_graph_json

    cases: list[CaseGraph] = []
    used: dict[str, int] = {}
    for p in paths:
        path = Path(p)
        if path.is_dir():
            gj = path / "graph.json"
            name = path.name
        else:
            gj = path
            # A bare `graph.json` stem is uninformative — name the case after its folder.
            name = path.parent.name if path.stem == "graph" else path.stem
        if not gj.is_file():
            raise FileNotFoundError(f"no graph.json at {p}")
        # Disambiguate collisions (two folders with the same name) deterministically.
        base = name or "case"
        used[base] = used.get(base, 0) + 1
        if used[base] > 1:
            name = f"{base}#{used[base]}"
        nodes, edges = load_graph_json(gj)
        cases.append(CaseGraph(name=name, nodes=nodes, edges=edges))
    return cases


def _relation_degree(case: CaseGraph) -> dict[str, int]:
    deg: dict[str, int] = {}
    for e in case.edges:
        if e.predicate in _PLUMBING:
            continue
        deg[e.subject] = deg.get(e.subject, 0) + 1
        deg[e.object] = deg.get(e.object, 0) + 1
    return deg


def shared_entities(cases: list[CaseGraph], *, min_cases: int = 2) -> list[SharedEntity]:
    """Entities that appear in at least ``min_cases`` cases — the cross-case bridges.

    Deterministic: identity is the content-addressed ``node_id``, so a match is exact. Ordered
    by how many cases the entity spans (most-connected first), then by name.
    """
    presence: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    degrees: dict[str, dict[str, int]] = {}
    for case in cases:
        deg = _relation_degree(case)
        for nid, name in case.entities().items():
            presence.setdefault(nid, []).append(case.name)
            names[nid] = name
            degrees.setdefault(nid, {})[case.name] = deg.get(nid, 0)
    shared = [
        SharedEntity(node_id=nid, name=names[nid], cases=sorted(cs), degree=degrees[nid])
        for nid, cs in presence.items()
        if len(cs) >= min_cases
    ]
    shared.sort(key=lambda s: (-len(s.cases), -sum(s.degree.values()), s.name))
    return shared


def entity_dossier(cases: list[CaseGraph], name: str) -> dict[str, Any]:
    """A cross-case profile for a named entity: which cases hold it, and its relations in each.

    Resolves ``name`` to entity node_id(s) by exact (case-insensitive) name match across all
    cases, so a query works even if the entity lives in only one of them.
    """
    target = name.strip().lower()
    node_ids: set[str] = set()
    display = name
    for case in cases:
        for nid, nm in case.entities().items():
            if nm.strip().lower() == target:
                node_ids.add(nid)
                display = nm
    per_case: list[dict[str, Any]] = []
    for case in cases:
        ents = case.entities()
        present = [nid for nid in node_ids if nid in ents]
        if not present:
            continue
        rels: list[dict[str, str]] = []
        for nid in present:
            rels.extend(case.relations(nid))
        per_case.append({"case": case.name, "relations": rels, "relation_count": len(rels)})
    return {
        "name": display,
        "node_ids": sorted(node_ids),
        "found": bool(node_ids),
        "in_cases": [c["case"] for c in per_case],
        "cases": per_case,
    }
