"""L5 orchestration: build records from the graph, block, score, cluster, resolve.

Produces canonical entities + non-destructive ``SAME_AS`` links. Only Organizations
and Persons are resolved (Money/Date/Email are literals). Deterministic default;
the Splink backend (``[er]`` extra) can replace scoring without changing this flow.
"""

from __future__ import annotations

from textgraph.l3_encoder_ie.canonicalize import normalize_name, strip_org_suffix
from textgraph.l5_entity_resolution.blocking import candidate_pairs, cross_product
from textgraph.l5_entity_resolution.clustering import cluster
from textgraph.l5_entity_resolution.model import Cluster, ERecord, ERResult, SameAs
from textgraph.l5_entity_resolution.scoring import MATCH_THRESHOLD, score_pair
from textgraph.l5_entity_resolution.similarity import acronym
from textgraph.store.base import Edge, Node, SourceSpan

_RESOLVABLE = frozenset({"Organization", "Person"})


def build_records(nodes: list[Node], edges: list[Edge]) -> list[ERecord]:
    """Derive ERecords (name signals + mention spans + graph neighbours) from the graph."""
    mention_spans: dict[str, list[SourceSpan]] = {}
    neighbors: dict[str, set[str]] = {}
    entity_ids = {n.node_id for n in nodes if "Entity" in n.labels and "Canonical" not in n.labels}
    for e in edges:
        if e.predicate == "MENTIONS" and e.object in entity_ids:
            mention_spans.setdefault(e.object, []).extend(e.source_spans)
        # Entity↔entity relations give the relational (shared-neighbour) signal.
        if e.subject in entity_ids and e.object in entity_ids:
            neighbors.setdefault(e.subject, set()).add(e.object)
            neighbors.setdefault(e.object, set()).add(e.subject)

    records: list[ERecord] = []
    for n in nodes:
        if "Entity" not in n.labels or "Canonical" in n.labels:
            continue
        etype = str(n.properties.get("etype", n.labels[1] if len(n.labels) > 1 else ""))
        if etype not in _RESOLVABLE:
            continue
        name = str(n.properties.get("name", n.node_id))
        norm = normalize_name(name)
        stripped = normalize_name(strip_org_suffix(name)) if etype == "Organization" else norm
        records.append(
            ERecord(
                entity_id=n.node_id,
                name=name,
                etype=etype,
                norm=norm,
                stripped=stripped or norm,
                acronym=acronym(name),
                mention_spans=tuple(mention_spans.get(n.node_id, [])),
                neighbors=frozenset(neighbors.get(n.node_id, set())),
            )
        )
    return sorted(records, key=lambda r: r.entity_id)


def _canonical_name(recs: list[ERecord]) -> str:
    # Most descriptive: most tokens, then longest, then alphabetical — deterministic.
    return sorted(recs, key=lambda r: (-len(r.name.split()), -len(r.name), r.name))[0].name


def run_er(records: list[ERecord], *, backend: str = "rules") -> ERResult:
    """Resolve ``records`` into canonical clusters + SAME_AS links."""
    if backend == "splink":
        from textgraph.l5_entity_resolution.splink_backend import score_pairs_splink

        scorer = score_pairs_splink
    else:
        scorer = None

    by_id = {r.entity_id: r for r in records}
    pairs = candidate_pairs(records)
    if scorer is not None:
        scored = scorer(by_id, pairs)
    else:
        scored = [(a, b, score_pair(by_id[a], by_id[b])) for a, b in pairs]
    matched = [(a, b, s) for a, b, s in scored if s >= MATCH_THRESHOLD]

    groups = cluster(by_id, matched, score_pair, cohesion_min=MATCH_THRESHOLD)

    clusters: list[Cluster] = []
    same_as: list[SameAs] = []
    for members in groups:
        recs = [by_id[m] for m in members]
        etype = recs[0].etype
        cname = _canonical_name(recs)
        cid = f"canonical:{etype}:{normalize_name(cname)}"
        clusters.append(
            Cluster(canonical_id=cid, canonical_name=cname, etype=etype, members=members)
        )
        for r in recs:
            best = max((score_pair(r, by_id[m]) for m in members if m != r.entity_id), default=1.0)
            if r.mention_spans:
                same_as.append(SameAs(r.entity_id, cid, round(best, 4), r.mention_spans[0]))
    return ERResult(
        clusters=clusters,
        same_as=same_as,
        candidate_pairs=len(pairs),
        cross_product=cross_product(len(records)),
    )
