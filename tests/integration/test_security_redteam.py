"""Phase 9 red-team: prove zero context-bleed through PPR / paths / summaries.

The gap analysis (§3.2) demands that security be enforced *inside* traversal — an
unauthorized node's transition probability must be zero — not bolted on as a post-filter.
These tests build a two-document corpus in which a ``public`` file and a ``secret`` file
share one entity (``Acme Corp``) and are joined by a cross-document chain
``Gamma Holdings -> Acme Corp -> Shadow LLC -> Phantom Bank``. A principal authorized for
the public document only must never see the secret entities, the secret relation, or a
path that routes through them — via any tool. The first test also asserts the leak is
*real* without a policy, so the suite can't pass by simply returning nothing.
"""

from pathlib import Path

from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build
from textgraph.security import RebacStore, RelationTuple, SecurityContext, SecurityPolicy

CORPUS = Path(__file__).parent.parent / "fixtures" / "corpora" / "secure"
SECRET = {"Shadow LLC", "Phantom Bank"}


def _doc_of(qe: QueryEngine, name: str) -> str:
    """The single document a public-/secret-only entity derives from."""
    nid = qe.resolve(name)
    assert nid is not None
    return sorted(qe._node_docs[nid])[0]


def _secured() -> tuple[QueryEngine, SecurityContext, str, str]:
    """Engine with a policy granting `alice` the public doc only (via group + folder)."""
    r = build(CORPUS)
    plain = QueryEngine(r.nodes, r.edges)
    public_doc = _doc_of(plain, "Gamma Holdings")  # public-only entity
    secret_doc = _doc_of(plain, "Shadow LLC")  # secret-only entity
    # Transitive policy path: alice -> group:analysts -> folder:cases(viewer) -> public doc.
    policy = SecurityPolicy(
        rebac=RebacStore(
            [
                RelationTuple("group:analysts", "member", "user:alice"),
                RelationTuple("folder:cases", "viewer", "group:analysts"),
                RelationTuple(f"doc:{public_doc}", "parent", "folder:cases"),
            ]
        )
    )
    qe = QueryEngine(r.nodes, r.edges, policy=policy)
    return qe, SecurityContext("alice"), public_doc, secret_doc


def _names(hits) -> set[str]:
    return {h.name for h in hits}


def test_leak_is_real_without_a_policy() -> None:
    # Control: with no access control, the secret entities DO surface — otherwise the
    # no-bleed assertions below would be vacuous.
    r = build(CORPUS)
    qe = QueryEngine(r.nodes, r.edges)
    hits = qe.search("shadow phantom transferred funds", k=10).hits
    assert _names(hits) & SECRET
    assert qe.path("Gamma Holdings", "Phantom Bank", k=1).paths  # cross-doc path exists


def test_search_ppr_does_not_leak_unauthorized_nodes() -> None:
    qe, ctx, _pub, secret_doc = _secured()
    res = qe.search("shadow phantom transferred funds", k=10, context=ctx)
    assert _names(res.hits).isdisjoint(SECRET)
    # No hit may carry provenance from the secret document (defence in depth).
    for h in res.hits:
        for c in h.citations:
            assert c.doc_id != secret_doc


def test_path_cannot_route_through_restricted_nodes() -> None:
    qe, ctx, _pub, _secret = _secured()
    # The only Gamma->Phantom route runs through the secret Shadow LLC edge -> blocked.
    assert qe.path("Gamma Holdings", "Phantom Bank", k=3, context=ctx).paths == []
    # A wholly-public path is still returned.
    assert qe.path("Delta Trust", "Acme Corp", k=1, context=ctx).paths


def test_neighbors_hides_edges_from_restricted_documents() -> None:
    qe, ctx, _pub, _secret = _secured()
    # Acme Corp is authorized (it appears in the public doc), but its TRANSFERRED->Shadow
    # relation is attested only by the secret doc and must not surface.
    nbrs = qe.neighbors("Acme Corp", context=ctx).neighbors
    others = {n.other_name for n in nbrs}
    assert "Gamma Holdings" in others  # public relation kept
    assert others.isdisjoint(SECRET)  # secret relation hidden
    assert all(n.predicate != "TRANSFERRED" for n in nbrs)


def test_communities_rosters_exclude_unauthorized_members() -> None:
    qe, ctx, _pub, _secret = _secured()
    members = {m for c in qe.communities(context=ctx).communities for m in c.members}
    assert members.isdisjoint(SECRET)


def test_vision_search_only_scores_authorized_pages() -> None:
    qe, ctx, _pub, secret_doc = _secured()
    hits = qe.vision_search("shadow phantom transfer", k=5, context=ctx).hits
    assert all(h.node_id != f"page:{secret_doc}" for h in hits)


def test_why_and_timeline_and_contradictions_hide_restricted_claims() -> None:
    qe, ctx, _pub, _secret = _secured()
    assert qe.why("Shadow LLC", context=ctx).claims == []
    assert qe.timeline("Shadow LLC", context=ctx).events == []
    # Nothing about the secret transfer leaks via any claim-bearing tool.
    assert qe.why("Acme Corp", context=ctx).claims  # public claims still visible
    assert all("Shadow" not in c.object for c in qe.why("Acme Corp", context=ctx).claims)


def test_default_path_is_unaffected_and_deterministic() -> None:
    r = build(CORPUS)
    unsecured = QueryEngine(r.nodes, r.edges).search("acme controls", k=5)
    # A policy-bearing engine with NO context presented behaves byte-identically (G1).
    qe, _ctx, _pub, _secret = _secured()
    assert qe.search("acme controls", k=5, context=None).to_dict() == unsecured.to_dict()
    # Secured queries are themselves deterministic.
    a = qe.search("acme controls", k=5, context=SecurityContext("alice")).to_dict()
    b = qe.search("acme controls", k=5, context=SecurityContext("alice")).to_dict()
    assert a == b
