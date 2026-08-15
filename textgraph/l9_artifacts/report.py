"""GRAPH_REPORT.md generator (L9, §12.3).

Human/agent orientation: corpus stats, node/edge breakdown, god nodes, rationale
and requirements, defined terms, coverage/orphans, and — the part that makes an
agent immediately effective — 10 suggested questions grounded in real graph nodes.
Deterministic: identical graph => identical report.
"""

from __future__ import annotations

from collections import Counter

from textgraph.core.layout import IngestResult
from textgraph.l9_artifacts.analytics_lite import Diagnostics
from textgraph.store.base import Edge, Node


def _name(n: Node) -> str:
    return str(n.properties.get("name", n.node_id))


def suggested_questions(nodes: list[Node], edges: list[Edge], diag: Diagnostics) -> list[str]:
    """Generate up to 10 grounded, answerable questions from real graph content."""
    by_label = diag.by_label
    questions: list[str] = []

    def take(label: str, template: str, limit: int) -> None:
        for n in sorted(by_label.get(label, []), key=lambda x: -diag.degree.get(x.node_id, 0))[
            :limit
        ]:
            q = template.format(name=_name(n))
            if q not in questions:
                questions.append(q)

    take("Organization", "How is “{name}” connected to other parties, and why?", 3)
    take("Person", "What role does {name} play in the network?", 1)
    take("Section", "What does the section “{name}” cover?", 2)
    take("Rationale", "Why was this decided: “{name}”?", 2)
    take("Term", "What is the definition of “{name}”?", 1)
    take("Requirement", "Which requirements does the corpus state (e.g. “{name}”)?", 1)
    take("Participant", "What did {name} discuss in the conversation?", 1)
    take("Money", "Which transfers involve the amount {name}?", 1)

    # Relationship-shaped questions grounded in real relation edges.
    preds = {e.predicate for e in edges}
    if "TRANSFERRED" in preds:
        questions.append("Follow the money: who transferred funds to whom?")
    if "CONTROLS" in preds or "BENEFICIAL_OWNER_OF" in preds:
        questions.append("Who ultimately controls or owns each entity?")
    if "DIRECTOR_OF" in preds:
        questions.append("Which individuals are directors or officers of which organizations?")

    # Deterministic structural fallbacks to always reach 10.
    fallbacks = [
        "What are the most connected concepts (god nodes) in this corpus?",
        "Which documents are most central to the graph?",
        "What rationale or decisions are recorded across the corpus?",
        "Which requirements (MUST/SHALL) does the corpus impose?",
        "Which sections or messages cross-reference each other?",
        "What terms or entities are defined across these documents?",
        "What contradictions or superseded statements exist (temporal view)?",
        "Which participants or documents are connected by shared references?",
    ]
    for f in fallbacks:
        if len(questions) >= 10:
            break
        if f not in questions:
            questions.append(f)
    return questions[:10]


_NON_RELATION_PREDS = frozenset(
    {"SAME_AS", "MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT", "CONTAINS"}
)


def _graph_health_section(nodes: list[Node], edges: list[Edge]) -> list[str]:
    """A compact health panel: the metrics that reveal a sparse or duplicated graph.

    These are the exact signals the 'floating dots' audit turned on — orphan rate,
    singleton-community rate, unlaid/unranked nodes, and duplicate-name candidates — surfaced
    so a thin graph is legible at a glance instead of only visible in the viewer.
    """
    entities = [n for n in nodes if "Entity" in n.labels]
    total = len(entities)
    if not total:
        return []

    eids = {n.node_id for n in entities}
    deg = dict.fromkeys(eids, 0)
    for e in edges:
        if e.predicate in _NON_RELATION_PREDS:
            continue
        if e.subject in deg:
            deg[e.subject] += 1
        if e.object in deg:
            deg[e.object] += 1
    orphans = sum(1 for v in deg.values() if v == 0)

    comm_size: dict[int, int] = {}
    for n in entities:
        cid = int(n.properties.get("community", -1))
        comm_size[cid] = comm_size.get(cid, 0) + 1
    singletons = sum(1 for s in comm_size.values() if s == 1)
    n_comm = len(comm_size)

    unlaid = sum(1 for n in entities if "x" not in n.properties or "y" not in n.properties)
    unranked = sum(1 for n in entities if int(n.properties.get("community", -1)) < 0)

    # Duplicate-name candidates: distinct entity ids that share a normalized name.
    by_key: dict[str, int] = {}
    for n in entities:
        key = str(n.properties.get("name", "")).strip().lower()
        if key:
            by_key[key] = by_key.get(key, 0) + 1
    dup_names = sum(c - 1 for c in by_key.values() if c > 1)

    def pct(x: int) -> str:
        return f"{100.0 * x / total:.0f}%"

    lines = ["", "## Graph health", "", "| metric | value |", "| --- | --- |"]
    lines.append(f"| entities | {total} |")
    lines.append(f"| orphans (degree 0) | {orphans} ({pct(orphans)}) |")
    lines.append(
        f"| singleton communities | {singletons} of {n_comm} "
        f"({pct(singletons) if total else '0%'}) |"
    )
    lines.append(f"| duplicate-name candidates | {dup_names} |")
    if unlaid or unranked:
        lines.append(f"| unlaid / unranked (bug) | {unlaid} / {unranked} |")
    hints = []
    if orphans > total * 0.4:
        hints.append(
            "Most entities are unconnected — build with `--co-occurrence` (or `--llm-extract`) "
            "to form a connected, clustered graph."
        )
    if dup_names:
        hints.append(
            "Some entities share a name — consider entity resolution (the `[er]` extra) to merge "
            "aliases."
        )
    if hints:
        lines += ["", *[f"> {h}" for h in hints]]
    return lines


def render_report(
    *,
    results: list[IngestResult],
    nodes: list[Node],
    edges: list[Edge],
    diag: Diagnostics,
    config_hash: str,
) -> str:
    node_by_id = {n.node_id: n for n in nodes}
    label_counts = {label: len(ns) for label, ns in diag.by_label.items()}
    pred_counts: dict[str, int] = {}
    for e in edges:
        pred_counts[e.predicate] = pred_counts.get(e.predicate, 0) + 1

    lines: list[str] = ["# Graph Report", ""]
    lines += [
        f"- **Documents:** {len(results)}",
        f"- **Nodes:** {len(nodes)}",
        f"- **Edges:** {len(edges)}",
        f"- **Config hash:** `{config_hash}`",
        "",
        "## Corpus",
        "",
        "| document | format | bytes | chunks |",
        "| --- | --- | --- | --- |",
    ]
    for ir in sorted(results, key=lambda r: r.source_name):
        lines.append(
            f"| {ir.source_name} | {ir.format} | {ir.canonical.raw_len} | {len(ir.chunks)} |"
        )

    lines += ["", "## Node types", "", "| label | count |", "| --- | --- |"]
    for label in sorted(label_counts):
        lines.append(f"| {label} | {label_counts[label]} |")

    lines += ["", "## Edge types", "", "| predicate | count |", "| --- | --- |"]
    for pred in sorted(pred_counts):
        lines.append(f"| {pred} | {pred_counts[pred]} |")

    lines += _graph_health_section(nodes, edges)

    # Entities (Phase 2): grouped by type, top by degree.
    _RELATION_PREDS = (
        "TRANSFERRED",
        "CONTROLS",
        "CONTROLLED_BY",
        "DIRECTOR_OF",
        "BENEFICIAL_OWNER_OF",
        "ASSOCIATED_WITH",
    )
    entity_nodes = [n for n in nodes if "Entity" in n.labels]
    if entity_nodes:
        lines += ["", "## Entities", "", "| type | entity | mentions |", "| --- | --- | --- |"]
        for n in sorted(entity_nodes, key=lambda n: (-diag.degree.get(n.node_id, 0), n.node_id))[
            :12
        ]:
            etype = n.properties.get("etype", (n.labels[1] if len(n.labels) > 1 else "?"))
            lines.append(f"| {etype} | {_name(n)} | {n.properties.get('mention_count', 0)} |")

    relations = [e for e in edges if e.predicate in _RELATION_PREDS]
    if relations:
        lines += ["", "## Key relationships", ""]
        for e in sorted(relations, key=lambda e: (e.predicate, e.subject, e.object))[:15]:
            subj = _name(node_by_id[e.subject]) if e.subject in node_by_id else e.subject
            obj = _name(node_by_id[e.object]) if e.object in node_by_id else e.object
            amount = e.properties.get("amount", "")
            neg = " (negated)" if e.properties.get("polarity") == "neg" else ""
            amt = f" — {amount}" if amount else ""
            lines.append(f"- **{subj}** → `{e.predicate}` → **{obj}**{amt} [`{e.tag}`]{neg}")

    # Resolved entities (Phase 3): canonical nodes and their SAME_AS members.
    canonical = [n for n in nodes if "Canonical" in n.labels]
    if canonical:
        members_of: dict[str, list[str]] = {}
        for e in edges:
            if e.predicate == "SAME_AS":
                members_of.setdefault(e.object, []).append(e.subject)
        lines += ["", "## Resolved entities (SAME_AS)", ""]
        for c in sorted(canonical, key=lambda n: n.node_id):
            member_names = [
                _name(node_by_id[m])
                for m in sorted(members_of.get(c.node_id, []))
                if m in node_by_id
            ]
            lines.append(f"- **{_name(c)}** ← {', '.join(member_names)}")

    lines += ["", "## God nodes (most connected)", ""]
    if diag.god_nodes:
        for nid, deg in diag.god_nodes[:5]:
            gn = node_by_id.get(nid)
            label = gn.labels[0] if gn and gn.labels else "?"
            lines.append(f"- **{_name(gn) if gn else nid}** ({label}) — degree {deg}")
    else:
        lines.append("_None yet._")

    # Communities (Phase 4, L7): auto-labelled clusters from label propagation.
    communities: dict[int, tuple[str, list[Node]]] = {}
    for n in nodes:
        cid = n.properties.get("community")
        if cid is None or "Entity" not in n.labels:
            continue
        label = str(n.properties.get("community_label", ""))
        communities.setdefault(int(cid), (label, []))[1].append(n)
    if communities:
        lines += ["", "## Communities (L7)", ""]
        for cid in sorted(communities):
            label, members = communities[cid]
            top = sorted(members, key=lambda x: -float(x.properties.get("pagerank", 0.0)))
            names = ", ".join(_name(m) for m in top[:5])
            lines.append(f"- **#{cid}** {label} — {len(members)} members: {names}")

    # Contradictions (Phase 4, L7): opposite-polarity claims on the same triple.
    contradicts = [e for e in edges if e.predicate == "CONTRADICTS"]
    if contradicts:
        lines += ["", f"## Contradictions (L7): {len(contradicts)}", ""]
        for e in sorted(contradicts, key=lambda e: e.edge_id)[:8]:
            a, b = node_by_id.get(e.subject), node_by_id.get(e.object)
            an = _name(a) if a else e.subject
            bn = _name(b) if b else e.object
            lines.append(f"- `{an}` conflicts with `{bn}`")

    # Conflicts: single-truth disagreements (same subject+predicate, different objects,
    # overlapping windows). Surfaced, never silently resolved (G3).
    conflicts = diag.by_label.get("Conflict", [])
    if conflicts:
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        conflicts = sorted(
            conflicts, key=lambda n: (order.get(str(n.properties.get("severity")), 3), n.node_id)
        )
        by_sev = Counter(str(n.properties.get("severity", "?")) for n in conflicts)
        sev_summary = ", ".join(f"{by_sev[s]} {s}" for s in ("HIGH", "MEDIUM", "LOW") if by_sev[s])
        lines += ["", f"## Conflicts: {len(conflicts)} ({sev_summary})", ""]
        lines.append("_Single-truth disagreements surfaced for review — not auto-resolved._")
        lines.append("")
        for n in conflicts[:8]:
            p = n.properties
            subj_node = node_by_id.get(str(p.get("subject_id", "")))
            subj = _name(subj_node) if subj_node else str(p.get("subject_id", ""))
            objs = [
                _name(node_by_id[o]) if o in node_by_id else str(o) for o in p.get("objects", [])
            ]
            lines.append(
                f"- **[{p.get('severity')}]** `{subj}` has competing "
                f"`{p.get('predicate')}` claims: {', '.join(f'`{o}`' for o in objs)}"
            )
            winner = p.get("resolved_object")
            if winner:
                wname = _name(node_by_id[winner]) if winner in node_by_id else str(winner)
                lines.append(
                    f"  - resolved by `{p.get('resolution_strategy')}` → **{wname}** "
                    f"(others superseded, not deleted)"
                )
            elif p.get("resolution_strategy"):
                lines.append(f"  - {p.get('resolution_note', 'unresolved')}")

    rationale = diag.by_label.get("Rationale", [])
    if rationale:
        lines += ["", "## Rationale & decisions", ""]
        for n in rationale[:8]:
            marker = n.properties.get("marker", "")
            lines.append(f"- `{marker}` — {_name(n)}")

    terms = diag.by_label.get("Term", [])
    if terms:
        lines += ["", "## Defined terms", ""]
        for n in sorted(terms, key=lambda x: _name(x)):
            lines.append(f"- **{_name(n)}**")

    lines += ["", f"## Coverage: {len(diag.orphans)} orphan node(s)", ""]
    if diag.orphans:
        for n in diag.orphans[:8]:
            lines.append(f"- {_name(n)} ({n.labels[0] if n.labels else '?'})")
    else:
        lines.append("_Every node is connected to the graph._")

    lines += ["", "## 10 questions this graph can answer well", ""]
    for i, q in enumerate(suggested_questions(nodes, edges, diag), 1):
        lines.append(f"{i}. {q}")

    return "\n".join(lines) + "\n"
