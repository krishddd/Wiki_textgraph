"""Conflict detection (truth discovery) — a first-class step, never a silent merge.

L5 already collapses duplicate *identities* (``Acme`` / ``ACME`` -> one node). What it
does not do is notice when two sources make **incompatible claims about the same
entity**: source A says Acme *controls* Beta, source B says Acme *controls* Gamma. For a
*single-truth* predicate (only one object can be correct at a time) that is a conflict an
investigator must see — not something the last-writer-wins merge should bury (G3).

This is the academic **truth-discovery** / veracity problem. TextGraph's version keeps
**detection** deterministic and auditable (this module), and leaves **resolution** as an
explicit, opt-in policy — the two-step separation the KG-construction literature converges
on. This module only ever *surfaces* a ``Conflict`` node; it never picks a winner and never
deletes a contending claim.

A conflict is: two or more positive ``Claim`` nodes of the same *single-truth* predicate,
same subject (after ``SAME_AS`` canonicalization), with **different objects**, whose
validity windows **overlap** (bi-temporal — sequential control changes like "CTO then VP"
are *not* conflicts, so overlapping windows are required before flagging; §1.4).

Deterministic: content-addressed ids, sorted output, no wall-clock (there is deliberately
no ``detected_at`` — a timestamp would break G1). Every emitted ``CONTENDS`` edge re-cites
its claim's byte span, so provenance still re-verifies (G3) and nothing is ``GENERATED``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from textgraph.core.content_address import hash_text
from textgraph.store.base import ConfidenceTag, Edge, Node, SourceSpan

# Pilot single-truth predicates: at a given time only one object can be correct. Multi-truth
# predicates (ASSOCIATED_WITH, a company's several directors) are deliberately excluded.
DEFAULT_SINGLE_TRUTH: tuple[str, ...] = ("BENEFICIAL_OWNER_OF", "CONTROLS", "DIRECTOR_OF")
# Legally consequential predicates escalate a conflict's severity.
_HIGH_SEVERITY = frozenset({"BENEFICIAL_OWNER_OF", "CONTROLS"})


@dataclass(frozen=True)
class _ClaimView:
    claim_id: str
    subject: str  # canonical
    predicate: str
    obj: str  # canonical
    t_valid: str | None
    t_invalid: str | None
    confidence: float


def _canonical_map(edges: list[Edge]) -> dict[str, str]:
    """alias entity id -> canonical id, from ``SAME_AS`` (member -> canonical)."""
    return {e.subject: e.object for e in edges if e.predicate == "SAME_AS"}


def _effective_windows(
    members: list[_ClaimView],
) -> dict[str, tuple[str | None, str | None]]:
    """Per-claim effective ``[start, end)`` validity window for overlap testing.

    ``end`` is the claim's stated ``t_invalid`` if the corpus dated the correction;
    otherwise, for a *single-truth* predicate, a strictly-later dated claim asserting a
    **different object** implicitly closes this one (single-truth sequencing — the later
    value is the current one). This is what stops a legitimate sequential role change
    ("director of Beta from 2019, of Gamma from 2021") from being flagged as a conflict
    (§1.4), while genuinely contemporaneous claims (same date, or undated) still overlap.
    """
    out: dict[str, tuple[str | None, str | None]] = {}
    for c in members:
        if c.t_invalid is not None:
            out[c.claim_id] = (c.t_valid, c.t_invalid)
            continue
        end: str | None = None
        if c.t_valid is not None:
            later = [
                o.t_valid
                for o in members
                if o.obj != c.obj and o.t_valid is not None and o.t_valid > c.t_valid
            ]
            end = min(later) if later else None
        out[c.claim_id] = (c.t_valid, end)
    return out


def _overlap(a: tuple[str | None, str | None], b: tuple[str | None, str | None]) -> bool:
    """True if half-open windows ``[start, end)`` overlap. ``None`` = open (-inf / +inf)."""
    a_start, a_end = a
    b_start, b_end = b
    left = a_start is None or b_end is None or a_start < b_end
    right = b_start is None or a_end is None or b_start < a_end
    return left and right


def _severity(predicate: str) -> str:
    return "HIGH" if predicate in _HIGH_SEVERITY else "MEDIUM"


def _claim_spans(edges: list[Edge]) -> dict[str, tuple[SourceSpan, ...]]:
    """claim_id -> its citing spans (from the reified SUBJECT_OF / HAS_OBJECT edges)."""
    spans: dict[str, tuple[SourceSpan, ...]] = {}
    for e in edges:
        if e.predicate == "SUBJECT_OF" and e.object.startswith("claim:"):
            spans.setdefault(e.object, e.source_spans)
        elif e.predicate == "HAS_OBJECT" and e.subject.startswith("claim:"):
            spans.setdefault(e.subject, e.source_spans)
    return spans


def detect_conflicts(
    nodes: list[Node],
    edges: list[Edge],
    *,
    single_truth: tuple[str, ...] = DEFAULT_SINGLE_TRUTH,
) -> tuple[list[Node], list[Edge]]:
    """Detect single-truth conflicts among ``Claim`` nodes; emit ``Conflict`` nodes + edges.

    Returns ``(conflict_nodes, conflict_edges)`` in deterministic id-sorted order. Pure
    function of the graph + the ``single_truth`` predicate set — cheap to re-run
    incrementally (G5). The caller merges the output in; nothing existing is mutated.
    """
    truth_set = frozenset(single_truth)
    if not truth_set:
        return [], []
    canon = _canonical_map(edges)
    name_of = {n.node_id: str(n.properties.get("name", n.node_id)) for n in nodes}
    spans_of = _claim_spans(edges)

    # Group positive single-truth claims by (canonical subject, predicate).
    groups: dict[tuple[str, str], list[_ClaimView]] = {}
    for n in nodes:
        if "Claim" not in n.labels:
            continue
        p = n.properties
        predicate = str(p.get("predicate", ""))
        if predicate not in truth_set or p.get("polarity", "pos") != "pos":
            continue
        subject = canon.get(str(p.get("subject", "")), str(p.get("subject", "")))
        obj = canon.get(str(p.get("object", "")), str(p.get("object", "")))
        view = _ClaimView(
            claim_id=n.node_id,
            subject=subject,
            predicate=predicate,
            obj=obj,
            t_valid=p.get("t_valid") if isinstance(p.get("t_valid"), str) else None,
            t_invalid=p.get("t_invalid") if isinstance(p.get("t_invalid"), str) else None,
            confidence=float(p.get("confidence", 0.0)),
        )
        groups.setdefault((subject, predicate), []).append(view)

    conflict_nodes: dict[str, Node] = {}
    conflict_edges: dict[str, Edge] = {}
    for (subject, predicate), members in sorted(groups.items()):
        windows = _effective_windows(members)
        # A claim contends if it overlaps some other claim asserting a *different* object.
        contending: dict[str, _ClaimView] = {}
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if a.obj != b.obj and _overlap(windows[a.claim_id], windows[b.claim_id]):
                    contending[a.claim_id] = a
                    contending[b.claim_id] = b
        if len(contending) < 2:
            continue
        claim_ids = sorted(contending)
        objects = sorted({v.obj for v in contending.values()})
        severity = _severity(predicate)
        conflict_id = "conflict:" + hash_text(f"{subject}|{predicate}|" + "|".join(objects))
        conflict_nodes[conflict_id] = Node(
            node_id=conflict_id,
            labels=("Conflict",),
            properties={
                "name": f"conflicting {predicate} of {name_of.get(subject, subject)}",
                "predicate": predicate,
                "subject_id": subject,
                "severity": severity,
                "object_count": len(objects),
                "objects": objects,
                "contending_claim_ids": claim_ids,
            },
        )
        for cid in claim_ids:
            spans = spans_of.get(cid, ())
            e = Edge(
                edge_id="edge:" + hash_text(f"{conflict_id}|CONTENDS|{cid}"),
                subject=conflict_id,
                predicate="CONTENDS",
                object=cid,
                tag=ConfidenceTag.INFERRED,
                confidence=round(contending[cid].confidence, 6),
                evidence_count=len(spans),
                source_spans=spans,
                properties={"severity": severity},
            )
            conflict_edges[e.edge_id] = e

    nodes_out = sorted(conflict_nodes.values(), key=lambda n: n.node_id)
    edges_out = sorted(conflict_edges.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out


# --- resolution (opt-in, pluggable, never destructive) -----------------------

STRATEGIES: tuple[str, ...] = ("most_recent", "voting", "credibility_weighted")


def _docs_of_claim(claim_id: str, spans_of: dict[str, tuple[SourceSpan, ...]]) -> list[str]:
    """Distinct source documents that assert a claim (from its citing spans)."""
    return sorted({s.doc_id for s in spans_of.get(claim_id, ())})


def _score_object(
    strategy: str,
    claim_ids: list[str],
    t_valid_of: dict[str, str | None],
    docs_of: dict[str, list[str]],
    credibility_by_doc: dict[str, float],
) -> tuple[float, str] | None:
    """Rank key for an object's claims under ``strategy`` (higher wins). ``None`` = unrankable.

    The second tuple element is a *deterministic* tie-break: the lexically-earliest source
    document backing the object (so equal-weight objects still resolve reproducibly). For
    ``most_recent`` the primary key is the latest in-text validity date; an object with no
    dated claim is unrankable and cannot win.
    """
    docs = sorted({d for cid in claim_ids for d in docs_of[cid]})
    tie = docs[0] if docs else ""
    if strategy == "most_recent":
        dates = [d for cid in claim_ids if (d := t_valid_of[cid]) is not None]
        if not dates:
            return None
        # Encode the max ISO date as a float-free ordinal via its own value in the tie slot;
        # primary stays 0.0 so the date (compared lexically) decides — packed into ``tie``.
        return (0.0, max(dates))
    if strategy == "voting":
        return (float(len(docs)), _neg(tie))
    # credibility_weighted: sum source credibility (default 1.0 -> degrades to voting).
    weight = sum(credibility_by_doc.get(d, 1.0) for d in docs)
    return (round(weight, 6), _neg(tie))


def _neg(s: str) -> str:
    """A tie-break helper so the lexically-*earliest* document wins a ``max`` comparison."""
    # Invert each char so that a smaller string yields a larger inverted string under max().
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def resolve_conflicts(
    nodes: list[Node],
    edges: list[Edge],
    *,
    strategy: str,
    credibility_by_doc: dict[str, float] | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Resolve detected ``Conflict`` nodes under ``strategy`` — non-destructively.

    Picks a winning *object* per conflict, then demotes every claim asserting a *losing*
    object: the claim keeps its identity and citation but gains ``superseded_by`` /
    ``resolved_by`` properties and a ``SUPERSEDED_BY`` edge pointing at the winning claim.
    Nothing is deleted (G3), and the four-tier ``ConfidenceTag`` taxonomy is untouched —
    ``SUPERSEDED`` is an orthogonal marker, not a fifth tier (plan open question #1).

    Returns ``(changed_nodes, new_edges)``: the updated ``Conflict`` nodes + demoted claim
    nodes, and the new ``SUPERSEDED_BY`` edges. Deterministic for a fixed strategy + config.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown resolution strategy: {strategy!r} (choose from {STRATEGIES})")
    credibility_by_doc = credibility_by_doc or {}
    canon = _canonical_map(edges)
    spans_of = _claim_spans(edges)
    claim_by_id = {n.node_id: n for n in nodes if "Claim" in n.labels}

    def canon_obj(cid: str) -> str:
        obj = str(claim_by_id[cid].properties.get("object", "")) if cid in claim_by_id else ""
        return canon.get(obj, obj)

    t_valid_of: dict[str, str | None] = {
        cid: (n.properties.get("t_valid") if isinstance(n.properties.get("t_valid"), str) else None)
        for cid, n in claim_by_id.items()
    }
    docs_of = {cid: _docs_of_claim(cid, spans_of) for cid in claim_by_id}

    changed: dict[str, Node] = {}
    new_edges: dict[str, Edge] = {}
    for cnode in sorted((n for n in nodes if "Conflict" in n.labels), key=lambda n: n.node_id):
        contending = [
            c for c in cnode.properties.get("contending_claim_ids", []) if c in claim_by_id
        ]
        if len(contending) < 2:
            continue
        by_object: dict[str, list[str]] = {}
        for cid in contending:
            by_object.setdefault(canon_obj(cid), []).append(cid)

        ranked: list[tuple[tuple[float, str], str]] = []
        for obj, cids in by_object.items():
            key = _score_object(strategy, cids, t_valid_of, docs_of, credibility_by_doc)
            if key is not None:
                ranked.append((key, obj))
        props = dict(cnode.properties)
        props["resolution_strategy"] = strategy
        if not ranked:
            props["resolved_claim_id"] = None
            props["resolved_object"] = None
            props["resolution_note"] = "unresolved: no orderable claim under strategy"
            props["superseded_claim_ids"] = []
            changed[cnode.node_id] = replace(cnode, properties=props)
            continue

        winner_object = max(ranked)[1]
        winner_claims = sorted(by_object[winner_object])
        resolved_claim_id = winner_claims[0]
        losers = sorted(cid for cid in contending if canon_obj(cid) != winner_object)

        props["resolved_object"] = winner_object
        props["resolved_claim_id"] = resolved_claim_id
        props["superseded_claim_ids"] = losers
        changed[cnode.node_id] = replace(cnode, properties=props)

        for loser in losers:
            lprops = dict(claim_by_id[loser].properties)
            lprops["superseded_by"] = resolved_claim_id
            lprops["resolved_by"] = strategy
            changed[loser] = replace(claim_by_id[loser], properties=lprops)
            spans = spans_of.get(loser, ())
            e = Edge(
                edge_id="edge:"
                + hash_text(f"{loser}|SUPERSEDED_BY|{resolved_claim_id}|{cnode.node_id}"),
                subject=loser,
                predicate="SUPERSEDED_BY",
                object=resolved_claim_id,
                tag=ConfidenceTag.INFERRED,
                confidence=float(claim_by_id[loser].properties.get("confidence", 0.0)),
                evidence_count=len(spans),
                source_spans=spans,
                properties={"strategy": strategy, "conflict_id": cnode.node_id},
            )
            new_edges[e.edge_id] = e

    nodes_out = sorted(changed.values(), key=lambda n: n.node_id)
    edges_out = sorted(new_edges.values(), key=lambda e: e.edge_id)
    return nodes_out, edges_out
