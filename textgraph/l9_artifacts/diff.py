"""Deterministic diff between two graph builds — ``what changed between A and B``.

For an AML/audit workflow the central question when a case folder grows is *what did adding
these documents change?* — which entities and relations appeared or vanished, which claims had
their confidence or validity window move, and which contradictions are new. This module answers
that as a pure set-difference over the two graphs.

The one thing that makes this reliable is that TextGraph ids are **content-addressed**: an
entity's ``node_id`` and a claim's id are hashes of their content, so the *same* real-world
fact keeps the *same* id across builds, and identity comparison Just Works. The single
exception is community ids, which are renumbered per build (§L7) — so communities are diffed by
**membership**, never by id.

Everything here is deterministic (sorted, no wall-clock) and read-only. It underpins the
``textgraph diff`` CLI, the ``watch`` webhook/watchlist alerts, and answer-comparison.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from textgraph.store.base import Edge, Node

# Edges that are graph plumbing, not assertions a user cares to see in a diff.
_PLUMBING = frozenset({"MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS"})


def _names(nodes: list[Node]) -> dict[str, str]:
    return {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}


def _entities(nodes: list[Node]) -> dict[str, Node]:
    return {n.node_id: n for n in nodes if "Entity" in n.labels}


def _claims(nodes: list[Node]) -> dict[tuple[str, str, str], Node]:
    """Claim nodes keyed by their (subject, predicate, object) — stable across builds."""
    out: dict[tuple[str, str, str], Node] = {}
    for n in nodes:
        if "Claim" in n.labels:
            p = n.properties
            out[(str(p.get("subject")), str(p.get("predicate")), str(p.get("object")))] = n
    return out


def _relation_keys(edges: list[Edge]) -> dict[tuple[str, str, str], Edge]:
    """Non-plumbing relation edges keyed by their (subject, predicate, object)."""
    out: dict[tuple[str, str, str], Edge] = {}
    for e in edges:
        if e.predicate in _PLUMBING or e.predicate == "CONTRADICTS":
            continue
        out[(e.subject, e.predicate, e.object)] = e
    return out


def _communities(nodes: list[Node]) -> dict[str, frozenset[str]]:
    """Map each entity id to the *set of names* it shares a community with (id-free)."""
    members: dict[int, list[str]] = defaultdict(list)
    name = _names(nodes)
    ent = _entities(nodes)
    for nid, node in ent.items():
        cid = int(node.properties.get("community", -1))
        if cid >= 0:
            members[cid].append(nid)
    out: dict[str, frozenset[str]] = {}
    for ids in members.values():
        peer_names = frozenset(name[i] for i in ids)
        for i in ids:
            # A node's community identity = the other names in its cluster.
            out[i] = peer_names - {name[i]}
    return out


def _contradiction_keys(
    edges: list[Edge], claims_by_id: dict[str, Node]
) -> dict[tuple[Any, Any], None]:
    """CONTRADICTS pairs keyed by the two claims' (subject, predicate, object) triples."""
    out: dict[tuple[Any, Any], None] = {}
    for e in edges:
        if e.predicate != "CONTRADICTS":
            continue
        a, b = claims_by_id.get(e.subject), claims_by_id.get(e.object)
        if a is None or b is None:
            continue

        def _triple(n: Node) -> tuple[str, str, str]:
            p = n.properties
            return (str(p.get("subject")), str(p.get("predicate")), str(p.get("object")))

        pair = tuple(sorted((_triple(a), _triple(b))))
        out[(pair[0], pair[1])] = None
    return out


@dataclass
class GraphDiff:
    """The additions, removals and changes between an ``old`` and a ``new`` graph."""

    added_entities: list[str] = field(default_factory=list)
    removed_entities: list[str] = field(default_factory=list)
    added_relations: list[dict[str, Any]] = field(default_factory=list)
    removed_relations: list[dict[str, Any]] = field(default_factory=list)
    changed_relations: list[dict[str, Any]] = field(default_factory=list)
    added_contradictions: list[dict[str, str]] = field(default_factory=list)
    removed_contradictions: list[dict[str, str]] = field(default_factory=list)
    community_moves: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.added_entities,
                self.removed_entities,
                self.added_relations,
                self.removed_relations,
                self.changed_relations,
                self.added_contradictions,
                self.removed_contradictions,
                self.community_moves,
            )
        )

    def counts(self) -> dict[str, int]:
        return {
            "added_entities": len(self.added_entities),
            "removed_entities": len(self.removed_entities),
            "added_relations": len(self.added_relations),
            "removed_relations": len(self.removed_relations),
            "changed_relations": len(self.changed_relations),
            "added_contradictions": len(self.added_contradictions),
            "removed_contradictions": len(self.removed_contradictions),
            "community_moves": len(self.community_moves),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"counts": self.counts(), **self.__dict__}

    def summary(self) -> str:
        """A one-line human summary (for a webhook/alert headline)."""
        c = self.counts()
        bits = []
        if c["added_entities"] or c["removed_entities"]:
            bits.append(f"entities +{c['added_entities']}/-{c['removed_entities']}")
        if c["added_relations"] or c["removed_relations"]:
            bits.append(f"relations +{c['added_relations']}/-{c['removed_relations']}")
        if c["changed_relations"]:
            bits.append(f"{c['changed_relations']} changed")
        if c["added_contradictions"]:
            bits.append(f"{c['added_contradictions']} new contradiction(s)")
        return "; ".join(bits) if bits else "no changes"


def graph_diff(
    old_nodes: list[Node],
    old_edges: list[Edge],
    new_nodes: list[Node],
    new_edges: list[Edge],
    *,
    entities: set[str] | None = None,
) -> GraphDiff:
    """Diff two builds. ``entities`` (a set of names) restricts the diff to a watchlist.

    Identity is by content-addressed id (entities, claims) except communities, which are
    compared by membership. Confidence is compared at 4 decimals to ignore float noise.
    """
    old_name, new_name = _names(old_nodes), _names(new_nodes)
    old_ent, new_ent = _entities(old_nodes), _entities(new_nodes)

    def _keep(name: str) -> bool:
        return entities is None or name in entities

    # -- entities: added / removed by id ---------------------------------------------
    added_e = sorted(new_name[i] for i in (set(new_ent) - set(old_ent)) if _keep(new_name[i]))
    removed_e = sorted(old_name[i] for i in (set(old_ent) - set(new_ent)) if _keep(old_name[i]))

    # -- relations: added / removed / changed by (subject, predicate, object) --------
    old_rel, new_rel = _relation_keys(old_edges), _relation_keys(new_edges)
    all_names = {**old_name, **new_name}

    def _rel(key: tuple[str, str, str]) -> dict[str, Any]:
        s, p, o = key
        return {"source": all_names.get(s, s), "predicate": p, "target": all_names.get(o, o)}

    def _touches(key: tuple[str, str, str]) -> bool:
        s, _p, o = key
        return _keep(all_names.get(s, s)) or _keep(all_names.get(o, o))

    added_r = [_rel(k) for k in sorted(set(new_rel) - set(old_rel)) if _touches(k)]
    removed_r = [_rel(k) for k in sorted(set(old_rel) - set(new_rel)) if _touches(k)]

    changed_r: list[dict[str, Any]] = []
    for k in sorted(set(old_rel) & set(new_rel)):
        if not _touches(k):
            continue
        oe, ne = old_rel[k], new_rel[k]
        deltas: dict[str, list[Any]] = {}
        if round(oe.confidence, 4) != round(ne.confidence, 4):
            deltas["confidence"] = [round(oe.confidence, 4), round(ne.confidence, 4)]
        if str(oe.tag) != str(ne.tag):
            deltas["tag"] = [str(oe.tag), str(ne.tag)]
        if oe.evidence_count != ne.evidence_count:
            deltas["evidence_count"] = [oe.evidence_count, ne.evidence_count]
        if deltas:
            changed_r.append({**_rel(k), "changes": deltas})

    # -- claims: validity-window / confidence moves (the bi-temporal signal) ----------
    old_claims, new_claims = _claims(old_nodes), _claims(new_nodes)
    for k in sorted(set(old_claims) & set(new_claims)):
        s, p, o = k
        if not (_keep(all_names.get(s, s)) or _keep(all_names.get(o, o))):
            continue
        op, np_ = old_claims[k].properties, new_claims[k].properties
        cdeltas: dict[str, list[Any]] = {}
        for prop in ("t_valid", "t_invalid", "polarity"):
            if op.get(prop) != np_.get(prop):
                cdeltas[prop] = [op.get(prop), np_.get(prop)]
        if cdeltas:
            changed_r.append(
                {
                    "source": all_names.get(s, s),
                    "predicate": p,
                    "target": all_names.get(o, o),
                    "changes": cdeltas,
                    "kind": "claim",
                }
            )

    # -- contradictions: new / resolved ----------------------------------------------
    old_claim_by_id = {n.node_id: n for n in old_nodes if "Claim" in n.labels}
    new_claim_by_id = {n.node_id: n for n in new_nodes if "Claim" in n.labels}
    old_contra = _contradiction_keys(old_edges, old_claim_by_id)
    new_contra = _contradiction_keys(new_edges, new_claim_by_id)

    def _contra_row(pair: tuple[Any, Any]) -> dict[str, str]:
        (s1, p1, o1), (s2, p2, o2) = pair
        return {
            "a": f"{all_names.get(s1, s1)} {p1} {all_names.get(o1, o1)}",
            "b": f"{all_names.get(s2, s2)} {p2} {all_names.get(o2, o2)}",
        }

    added_c = [_contra_row(k) for k in sorted(set(new_contra) - set(old_contra))]
    removed_c = [_contra_row(k) for k in sorted(set(old_contra) - set(new_contra))]

    # -- community membership moves (id-free) ----------------------------------------
    old_comm, new_comm = _communities(old_nodes), _communities(new_nodes)
    moves: list[dict[str, Any]] = []
    for nid in sorted(set(old_ent) & set(new_ent)):
        name = new_name[nid]
        if not _keep(name):
            continue
        before, after = old_comm.get(nid, frozenset()), new_comm.get(nid, frozenset())
        if before != after:
            joined = sorted(after - before)
            left = sorted(before - after)
            if joined or left:
                moves.append({"entity": name, "joined": joined, "left": left})

    return GraphDiff(
        added_entities=added_e,
        removed_entities=removed_e,
        added_relations=added_r,
        removed_relations=removed_r,
        changed_relations=changed_r,
        added_contradictions=added_c,
        removed_contradictions=removed_c,
        community_moves=moves,
    )
