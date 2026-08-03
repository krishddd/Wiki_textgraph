"""Human-review audit for entity resolution (`textgraph er audit`, §8.4)."""

from __future__ import annotations

from textgraph.l5_entity_resolution.metrics import reduction_ratio
from textgraph.l5_entity_resolution.model import ERecord, ERResult


def render_audit(er: ERResult, records: list[ERecord]) -> str:
    by_id = {r.entity_id: r for r in records}
    score_by_member = {sa.member_id: sa.score for sa in er.same_as}
    merged = sum(len(c.members) for c in er.clusters)
    lines = [
        "# Entity Resolution Audit",
        "",
        f"- **Entities considered:** {len(records)}",
        f"- **Clusters (merges):** {len(er.clusters)} covering {merged} entities",
        f"- **Candidate pairs:** {er.candidate_pairs} of {er.cross_product} "
        f"(reduction ratio {reduction_ratio(er.candidate_pairs, er.cross_product):.4f})",
        "",
        "## Proposed SAME_AS clusters",
        "",
    ]
    if not er.clusters:
        lines.append("_No entities were merged._")
    for c in sorted(er.clusters, key=lambda c: c.canonical_id):
        lines.append(f"### {c.canonical_name}  ({c.etype}, {len(c.members)} members)")
        for mid in c.members:
            rec = by_id.get(mid)
            name = rec.name if rec else mid
            score = score_by_member.get(mid, 1.0)
            lines.append(f"- {name}  -> SAME_AS (score {score:.3f})")
        lines.append("")
    lines.append(
        "_Merges are non-destructive: original entities are preserved and each "
        "SAME_AS edge cites the mention span that supports it._"
    )
    return "\n".join(lines) + "\n"
