"""L4 synthesis — GENERATED community summaries (Phase 6, opt-in).

For the largest L7 communities, this asks the LLM for a 1-2 sentence summary grounded
*only* in the facts we pass it (member entities + the relations among them), and emits
a ``Summary`` node tagged ``GENERATED`` plus ``SUMMARIZES`` edges to the community's
most central members. GENERATED is the whole point: this content is model-authored, so
it is quarantined by tag (G4) — it can never be mistaken for an extracted/cited fact,
is exempt from provenance re-verification, and only appears when ``--llm`` is set.

Hard-budgeted (``max_calls`` communities, biggest first) and cached, so cost is bounded
(G7) and a warm rebuild is reproducible.
"""

from __future__ import annotations

from textgraph.core.content_address import hash_text
from textgraph.l4_llm_optional.cache import PromptCache
from textgraph.l4_llm_optional.client import LLMClient, LLMError
from textgraph.l7_analytics.analyze import Analytics
from textgraph.store.base import ConfidenceTag, Edge, Node

_SYSTEM = (
    "You are a financial-crime analyst. In 1-2 sentences, summarize the cluster of "
    "entities described below using ONLY the facts provided. Do not speculate or invent "
    "names, amounts, or relationships. Be concise and neutral."
)
_NON_RELATION = frozenset(
    {"SAME_AS", "MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTRADICTS", "SUPERSEDES"}
)


def _name_map(nodes: list[Node]) -> dict[str, str]:
    return {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}


def _community_facts(members: list[str], names: dict[str, str], relations: list[Edge]) -> str:
    member_names = sorted(names.get(m, m) for m in members)
    lines = [f"Entities: {', '.join(member_names)}", "Relationships:"]
    member_set = set(members)
    rel_lines = sorted(
        f"- {names.get(e.subject, e.subject)} {e.predicate} {names.get(e.object, e.object)}"
        for e in relations
        if e.subject in member_set and e.object in member_set
    )
    lines.extend(rel_lines or ["- (none stated)"])
    return "\n".join(lines)


def synthesize(
    nodes: list[Node],
    edges: list[Edge],
    analytics: Analytics,
    client: LLMClient,
    cache: PromptCache,
    *,
    max_calls: int = 8,
) -> tuple[list[Node], list[Edge]]:
    """Return ``(generated_nodes, generated_edges)`` — GENERATED community summaries."""
    names = _name_map(nodes)
    relations = [e for e in edges if e.predicate not in _NON_RELATION]

    members_by_comm: dict[int, list[str]] = {}
    for nid, cid in analytics.community_of.items():
        members_by_comm.setdefault(cid, []).append(nid)

    # Biggest communities first (ties by id); hard-cap the number of LLM calls.
    ordered = sorted(members_by_comm.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:max_calls]

    gen_nodes: dict[str, Node] = {}
    gen_edges: dict[str, Edge] = {}
    for cid, members in ordered:
        if len(members) < 2:
            continue  # a single-entity "community" isn't worth a summary
        facts = _community_facts(members, names, relations)
        key = cache.key(client.model, _SYSTEM, facts, client.temperature, client.max_tokens)
        summary = cache.get(key)
        if summary is None:
            try:
                summary = client.complete(_SYSTEM, facts)
            except LLMError:
                continue  # skip this community; never fail the whole build on one call
            cache.put(key, summary)
        if not summary:
            continue

        sid = "summary:" + hash_text(f"{client.model}|{cid}|" + "|".join(sorted(members)))
        gen_nodes[sid] = Node(
            node_id=sid,
            labels=("Summary",),
            properties={
                "name": summary[:80],
                "text": summary,
                "tag": str(ConfidenceTag.GENERATED),
                "community": cid,
                "community_label": analytics.community_labels.get(cid, ""),
                "model": client.model,
            },
        )
        # Link to the community's most central members (GENERATED, no source spans).
        central = sorted(
            members,
            key=lambda m: (-analytics.pagerank.get(m, 0.0), m),
        )[:3]
        for m in central:
            eid = "edge:" + hash_text(f"{sid}|SUMMARIZES|{m}")
            gen_edges[eid] = Edge(
                edge_id=eid,
                subject=sid,
                predicate="SUMMARIZES",
                object=m,
                tag=ConfidenceTag.GENERATED,
                confidence=0.5,
                evidence_count=0,
                source_spans=(),
                properties={},
            )

    nodes_out = sorted(gen_nodes.values(), key=lambda n: n.node_id)
    edges_out = sorted(gen_edges.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out
