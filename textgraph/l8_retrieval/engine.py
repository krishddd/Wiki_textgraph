"""L8 QueryEngine — the agent's whole view of the graph (G6).

Built once from ``(nodes, edges)`` (i.e. straight from ``graph.json``), it exposes
the eight typed tools an agent calls instead of writing Cypher: ``search``,
``neighbors``, ``path``, ``why``, ``timeline``, ``contradictions``, ``communities``,
``stats``. Each returns a bounded, cited result object from :mod:`.model` — never a
raw row dump.

``search`` is hybrid: pure-Python BM25 over chunk passages (the lexical signal) fused
by Reciprocal Rank Fusion with Personalized PageRank over the dual-node entity+chunk
graph (the associative signal), with lightweight local/global routing. ``path`` is
maximum-likelihood (shortest path under ``-log(confidence)`` weights), so the returned
chain is the most trustworthy one, not merely the shortest. Everything is
deterministic (G1) and every factual row cites re-verifiable bytes (G3).
"""

from __future__ import annotations

import heapq
import math
from typing import Any

from textgraph.l7_analytics.algorithms import build_adjacency, pagerank
from textgraph.l8_retrieval.bm25 import BM25Index, tokenize
from textgraph.l8_retrieval.model import (
    ChainHop,
    Citation,
    ClaimView,
    CommunitiesResult,
    CommunityView,
    ConflictsResult,
    ConflictView,
    ContradictionPair,
    ContradictionsResult,
    DecisionChainResult,
    DecisionHit,
    DecisionRef,
    GraphPath,
    NeighborEdge,
    NeighborsResult,
    PathResult,
    PathStep,
    SearchHit,
    SearchResult,
    SimilarDecisionsResult,
    StatsResult,
    TimelineResult,
    WhyResult,
    budget_items,
)
from textgraph.l8_retrieval.rerank import rerank
from textgraph.security.context import SecurityContext
from textgraph.security.policy import SecurityPolicy
from textgraph.store.base import Edge, Node

_RRF_K = 60  # Reciprocal Rank Fusion damping constant (standard default).
# Edges that are graph plumbing, not entity-to-entity relations, kept out of the
# relation adjacency used by path().
_NON_RELATION = frozenset({"SAME_AS", "MENTIONS", "HAS_CHUNK", "SUBJECT_OF", "HAS_OBJECT"})
# Causal predicates between Decision nodes (the decision-provenance chain).
_CAUSAL_PREDICATES = frozenset({"CAUSED", "INFLUENCED", "PRECEDENT_FOR"})
# Edges hidden from neighbors(): reification plumbing + membership/provenance edges,
# so an entity's semantic relations surface instead of being buried under MENTIONS.
_HIDDEN_NEIGHBORS = frozenset({"SUBJECT_OF", "HAS_OBJECT", "MENTIONS", "HAS_CHUNK"})


def _citations(edge: Edge) -> list[Citation]:
    return [Citation(s.doc_id, s.start, s.end, s.hash) for s in edge.source_spans]


class QueryEngine:
    """Typed, bounded, cited retrieval over an assembled TextGraph."""

    def __init__(
        self, nodes: list[Node], edges: list[Edge], *, policy: SecurityPolicy | None = None
    ) -> None:
        # Enterprise FGAC (Phase 9): when set, tools accept a per-call SecurityContext and
        # enforce it inside traversal (unauthorized transition probability -> 0). None =>
        # every method behaves byte-identically to the un-secured engine (default install).
        self._policy = policy
        self._node = {n.node_id: n for n in nodes}
        self._edges = sorted(edges, key=lambda e: e.edge_id)
        self._entity_ids = frozenset(n.node_id for n in nodes if "Entity" in n.labels)
        self._chunk_ids = frozenset(n.node_id for n in nodes if "Chunk" in n.labels)
        self._claim_ids = frozenset(n.node_id for n in nodes if "Claim" in n.labels)
        self._decision_ids = frozenset(n.node_id for n in nodes if "Decision" in n.labels)

        # Name lookup for resolving a free-text handle to an entity id.
        self._by_name: dict[str, list[str]] = {}
        for nid in sorted(self._entity_ids):
            name = self._name(nid).lower().strip()
            self._by_name.setdefault(name, []).append(nid)

        # BM25 over chunk passages.
        self._bm25 = BM25Index(
            [(cid, str(self._node[cid].properties.get("text", ""))) for cid in self._chunk_ids]
        )

        # Dual-node PPR graph: entities + chunks joined by relations / SAME_AS /
        # chunk-mention edges (weight = confidence).
        ppr_ids = sorted(self._entity_ids | self._chunk_ids)
        ppr_edges: list[tuple[str, str, float]] = []
        for e in self._edges:
            if (
                e.subject in self._node
                and e.object in self._node
                and (
                    e.subject in (self._entity_ids | self._chunk_ids)
                    and e.object in (self._entity_ids | self._chunk_ids)
                )
            ):
                ppr_edges.append((e.subject, e.object, max(1e-6, e.confidence)))
        self._ppr_ids = ppr_ids
        self._ppr_adj = build_adjacency(ppr_ids, ppr_edges)

        # chunk -> mentioned entities, and citation of each chunk (its HAS_CHUNK span).
        self._chunk_entities: dict[str, list[str]] = {}
        self._chunk_citation: dict[str, Citation] = {}
        self._entity_citation: dict[str, Citation] = {}
        for e in self._edges:
            if e.predicate == "MENTIONS" and e.subject in self._chunk_ids:
                self._chunk_entities.setdefault(e.subject, []).append(e.object)
            if e.predicate == "HAS_CHUNK" and e.source_spans:
                self._chunk_citation[e.object] = _citations(e)[0]
            if e.predicate == "MENTIONS" and e.subject.startswith("doc:") and e.source_spans:
                self._entity_citation.setdefault(e.object, _citations(e)[0])

        # Relation adjacency (entity graph) for neighbors/path, carrying the edge.
        self._rel_adj: dict[str, list[tuple[str, Edge]]] = {}
        for e in self._edges:
            if e.predicate in _NON_RELATION:
                continue
            if e.subject in self._entity_ids and e.object in self._entity_ids:
                self._rel_adj.setdefault(e.subject, []).append((e.object, e))
                self._rel_adj.setdefault(e.object, []).append((e.subject, e))

        # Claim reconstruction: claim_id -> citations (from its SUBJECT_OF/HAS_OBJECT).
        self._claim_citation: dict[str, list[Citation]] = {}
        # node_id -> set of doc_ids it is cited in (for doc-scoped rationale in `why`).
        self._node_docs: dict[str, set[str]] = {}
        for e in self._edges:
            if e.predicate == "SUBJECT_OF" and e.object in self._claim_ids:
                self._claim_citation.setdefault(e.object, _citations(e))
            elif e.predicate == "HAS_OBJECT" and e.subject in self._claim_ids:
                self._claim_citation.setdefault(e.subject, _citations(e))
            docs = {s.doc_id for s in e.source_spans}
            if docs:
                self._node_docs.setdefault(e.subject, set()).update(docs)
                self._node_docs.setdefault(e.object, set()).update(docs)
        # All documents any node derives from — the universe the access guard filters (G9).
        self._all_docs = frozenset(d for docs in self._node_docs.values() for d in docs)

        # Decision-provenance state: statement search + causal adjacency (both directions).
        self._decision_bm25 = BM25Index(
            [(did, self._decision_text(did)) for did in sorted(self._decision_ids)]
        )
        self._decision_citation: dict[str, list[Citation]] = {}
        self._causal_out: dict[str, list[tuple[str, Edge]]] = {}  # cause -> [(effect, edge)]
        self._causal_in: dict[str, list[tuple[str, Edge]]] = {}  # effect -> [(cause, edge)]
        for e in self._edges:
            if e.subject not in self._decision_ids:
                continue
            if e.predicate == "DERIVED_FROM" and e.source_spans:
                self._decision_citation.setdefault(e.subject, _citations(e))
            elif e.predicate in _CAUSAL_PREDICATES and e.object in self._decision_ids:
                self._causal_out.setdefault(e.subject, []).append((e.object, e))
                self._causal_in.setdefault(e.object, []).append((e.subject, e))

        # Lazily-built vision (page) retrieval state.
        self._pages_built: list[Any] | None = None
        self._vision: Any = None

    def _decision_text(self, did: str) -> str:
        p = self._node[did].properties
        return str(p.get("statement", p.get("name", "")))

    # -- graph view (for the visual console) ------------------------------------

    def graph_view(self, *, max_nodes: int = 600) -> dict[str, Any]:
        """Render payload: laid-out entity nodes + their relations, capped by PageRank.

        Bounded for large graphs (G7): keeps the top ``max_nodes`` entities by PageRank
        and the edges induced on them, reporting how many were dropped rather than
        truncating silently.
        """
        ranked = sorted(
            self._entity_ids,
            key=lambda nid: (-float(self._node[nid].properties.get("pagerank", 0.0)), nid),
        )
        kept = set(ranked[:max_nodes])
        nodes = [
            {
                "id": nid,
                "name": self._name(nid),
                "x": float(self._node[nid].properties.get("x", 0.0)),
                "y": float(self._node[nid].properties.get("y", 0.0)),
                "community": int(self._node[nid].properties.get("community", -1)),
                "community_label": str(self._node[nid].properties.get("community_label", "")),
                "pagerank": round(float(self._node[nid].properties.get("pagerank", 0.0)), 6),
                "etype": str(self._node[nid].properties.get("etype", "")),
            }
            for nid in sorted(kept)
        ]
        # Attach each relation's claim-validity window so the console can scrub time.
        from textgraph.l6_graph_model import claim_id_for

        edges = []
        dates: set[str] = set()
        for e in self._edges:
            if e.predicate in _NON_RELATION or e.subject not in kept or e.object not in kept:
                continue
            claim = self._node.get(claim_id_for(e))
            t_valid = claim.properties.get("t_valid") if claim else None
            t_invalid = claim.properties.get("t_invalid") if claim else None
            if isinstance(t_valid, str):
                dates.add(t_valid)
            if isinstance(t_invalid, str):
                dates.add(t_invalid)
            edges.append(
                {
                    "source": e.subject,
                    "target": e.object,
                    "predicate": e.predicate,
                    "tag": str(e.tag),
                    "confidence": round(e.confidence, 4),
                    "t_valid": t_valid,
                    "t_invalid": t_invalid,
                }
            )
        # Community roster (size = all entities in the community, not just the kept ones).
        sizes: dict[int, int] = {}
        labels: dict[int, str] = {}
        for nid in sorted(self._entity_ids):
            cid = int(self._node[nid].properties.get("community", -1))
            if cid < 0:
                continue
            sizes[cid] = sizes.get(cid, 0) + 1
            labels[cid] = str(self._node[nid].properties.get("community_label", ""))
        communities = [
            {"community_id": cid, "label": labels[cid], "size": sizes[cid]}
            for cid in sorted(sizes, key=lambda c: (-sizes[c], c))
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "communities": communities,
            "dates": sorted(dates),  # scrubber stops for the temporal slider
            "shown": len(nodes),
            "total": len(self._entity_ids),
            "truncated": len(self._entity_ids) > len(nodes),
        }

    # -- helpers ----------------------------------------------------------------

    def _name(self, node_id: str) -> str:
        n = self._node.get(node_id)
        return str(n.properties.get("name", node_id)) if n else node_id

    # -- enterprise FGAC (Phase 9) ---------------------------------------------

    def _auth(
        self, context: SecurityContext | None
    ) -> tuple[frozenset[str] | None, frozenset[str] | None]:
        """Resolve ``(authorized_node_ids, authorized_docs)`` for a context.

        Returns ``(None, None)`` when no policy is attached or no context is presented —
        the un-secured fast path (no overhead, byte-identical results). Otherwise every
        node whose provenance touches an authorized document is authorized; a node with no
        known provenance is denied (secure default), so restricted content can never seed
        or be reached by a walk (§3.2).
        """
        if self._policy is None or context is None:
            return None, None
        ok_docs = self._policy.authorized_docs(context, self._all_docs)
        nodes = frozenset(nid for nid, docs in self._node_docs.items() if docs & ok_docs)
        return nodes, ok_docs

    def _edge_ok(
        self, e: Edge, nodes: frozenset[str] | None, ok_docs: frozenset[str] | None
    ) -> bool:
        """An edge is traversable/visible iff both endpoints and its provenance are authorized.

        Requiring the edge's *own* source documents to be authorized (not just its
        endpoints) stops a restricted relation between two otherwise-visible entities from
        leaking through neighbors/path — the relation is knowledge from the document that
        attests it.
        """
        if nodes is None:
            return True
        if e.subject not in nodes or e.object not in nodes:
            return False
        edocs = {s.doc_id for s in e.source_spans}
        return not edocs or bool(ok_docs and (edocs & ok_docs))

    def resolve(self, handle: str, *, context: SecurityContext | None = None) -> str | None:
        """Resolve a node id or free-text name to a node id (deterministic).

        When a policy is attached and ``context`` is given, resolution is restricted to
        authorized nodes, so a caller can never learn that a restricted entity exists (or
        surface its name) by resolving a handle that happens to match it (§3.2).
        """
        nodes, _ = self._auth(context)

        def ok(nid: str) -> bool:
            return nodes is None or nid in nodes

        if handle in self._node and ok(handle):
            return handle
        key = handle.lower().strip()
        if key in self._by_name:
            allowed = sorted(n for n in self._by_name[key] if ok(n))
            if allowed:
                return allowed[0]
        # Fall back to best token-overlap entity, tie-broken by PageRank then id.
        q = set(tokenize(handle))
        if not q:
            return None
        best: tuple[int, float, str] | None = None
        for nid in sorted(self._entity_ids):
            if not ok(nid):
                continue
            overlap = len(q & set(tokenize(self._name(nid))))
            if overlap == 0:
                continue
            pr = float(self._node[nid].properties.get("pagerank", 0.0))
            cand = (overlap, pr, nid)
            if best is None or cand > (best[0], best[1], best[2]):
                best = cand
        return best[2] if best else None

    def _claim_view(self, claim_id: str) -> ClaimView | None:
        n = self._node.get(claim_id)
        if n is None:
            return None
        p = n.properties
        return ClaimView(
            claim_id=claim_id,
            subject=self._name(str(p.get("subject", ""))),
            predicate=str(p.get("predicate", "")),
            object=self._name(str(p.get("object", ""))),
            polarity=str(p.get("polarity", "pos")),
            modality=str(p.get("modality", "asserted")),
            confidence=float(p.get("confidence", 0.0)),
            t_valid=(str(tv) if (tv := p.get("t_valid")) is not None else None),
            t_invalid=(str(ti) if (ti := p.get("t_invalid")) is not None else None),
            tag=str(p.get("tag", "")),
            citations=self._claim_citation.get(claim_id, []),
        )

    # -- tool 1: search ---------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        max_tokens: int = 1500,
        rerank_backend: str = "builtin",
        context: SecurityContext | None = None,
    ) -> SearchResult:
        """Hybrid BM25 + Personalized-PageRank search: RRF fusion, rerank, route.

        When a policy is attached and ``context`` is given, retrieval is security-aware:
        the PPR walk runs on a graph masked to the principal's authorized nodes, so an
        unauthorized node's transition probability is zero and cannot influence centrality
        or surface as a hit (§3.2 — enforcement in the walk, not a post-filter).
        """
        nodes, _ok_docs = self._auth(context)
        bm = self._bm25.search(query, k=max(k * 2, 10))
        if nodes is not None:
            bm = [(cid, s) for cid, s in bm if cid in nodes]
        chunk_rank = {cid: i for i, (cid, _) in enumerate(bm)}

        # Seed PPR: query-name entities + entities in the top lexical chunks.
        seed: dict[str, float] = {}
        for nid in sorted(self._entity_ids):
            if nodes is not None and nid not in nodes:
                continue
            overlap = len(set(tokenize(query)) & set(tokenize(self._name(nid))))
            if overlap:
                seed[nid] = seed.get(nid, 0.0) + float(overlap)
        for cid, score in bm:
            seed[cid] = seed.get(cid, 0.0) + max(score, 0.0)
            for ent in self._chunk_entities.get(cid, []):
                if nodes is not None and ent not in nodes:
                    continue
                seed[ent] = seed.get(ent, 0.0) + max(score, 0.0) * 0.5
        # Security-aware transition matrix: drop every edge into an unauthorized node so
        # its transition probability is 0 (§3.2). The default path reuses the shared graph.
        if nodes is not None:
            ppr_ids = [n for n in self._ppr_ids if n in nodes]
            ppr_adj = {
                n: [(m, w) for m, w in self._ppr_adj.get(n, []) if m in nodes] for n in ppr_ids
            }
        else:
            ppr_ids, ppr_adj = self._ppr_ids, self._ppr_adj
        # Only rank entities by PPR when the query actually seeded the walk. With an
        # empty seed the teleport is uniform, so PPR would just re-emit degree
        # centrality — surfacing arbitrary "hits" for a query that matched nothing.
        ppr = pagerank(ppr_ids, ppr_adj, personalization=seed) if seed else {}
        ent_ranking = sorted(
            (nid for nid in self._entity_ids if ppr.get(nid, 0.0) > 0),
            key=lambda nid: (-ppr.get(nid, 0.0), nid),
        )
        entity_rank = {nid: i for i, nid in enumerate(ent_ranking[: max(k * 2, 10)])}

        # Reciprocal Rank Fusion across the chunk (lexical) and entity (graph) lists.
        rrf: dict[str, float] = {}
        for cid, rank in chunk_rank.items():
            rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
        for nid, rank in entity_rank.items():
            rrf[nid] = rrf.get(nid, 0.0) + 1.0 / (_RRF_K + rank)

        routed = self.resolve(query)
        routing = "local" if routed and routed in entity_rank else "global"

        # Build hits for a wide candidate pool, rerank, THEN take the top k — so the
        # second stage can rescue a relevant entity the raw fusion had buried.
        fused = sorted(rrf.items(), key=lambda kv: (-kv[1], kv[0]))[: max(k * 4, 24)]
        candidates: list[SearchHit] = []
        for node_id, score in fused:
            if node_id in self._chunk_ids:
                snippet = str(self._node[node_id].properties.get("text", ""))[:280]
                cit = self._chunk_citation.get(node_id)
                candidates.append(
                    SearchHit(
                        node_id, "chunk", self._name(node_id), score, snippet, [cit] if cit else []
                    )
                )
            elif node_id in self._entity_ids:
                label = str(self._node[node_id].properties.get("community_label", ""))
                snippet = f"community: {label}" if routing == "global" and label else ""
                cit = self._entity_citation.get(node_id)
                candidates.append(
                    SearchHit(
                        node_id, "entity", self._name(node_id), score, snippet, [cit] if cit else []
                    )
                )
        ranked = rerank(query, candidates, backend=rerank_backend)[:k]
        texts = [(h.snippet or h.name) for h in ranked]
        kept, truncated = budget_items(ranked, texts, max_tokens)
        return SearchResult(query=query, routing=routing, hits=kept, truncated=truncated)

    # -- vision: late-interaction page retrieval (Phase 8) ----------------------

    def _pages(self) -> list[Any]:
        """Build one page per document (chunk texts concatenated in order); cached."""
        if self._pages_built is not None:
            return self._pages_built
        from textgraph.l8_retrieval.vision import VisionPage

        groups: dict[str, list[tuple[int, str, str]]] = {}
        for cid in self._chunk_ids:
            p = self._node[cid].properties
            doc = str(p.get("doc_id", ""))
            groups.setdefault(doc, []).append((int(p.get("index", 0)), str(p.get("text", "")), cid))
        pages: list[VisionPage] = []
        for doc, items in sorted(groups.items()):
            items.sort()
            text = "\n".join(t for _, t, _ in items)
            cit = self._chunk_citation.get(items[0][2])
            pages.append(
                VisionPage(
                    page_id=f"page:{doc}", doc_id=doc, name=text[:60], text=text, citation=cit
                )
            )
        self._pages_built = pages
        return pages

    def vision_search(
        self,
        query: str,
        *,
        k: int = 5,
        max_tokens: int = 1500,
        embedder: Any = None,
        context: SecurityContext | None = None,
    ) -> SearchResult:
        """Rank documents-as-pages by MaxSim late interaction (ColPali-style).

        Uses the deterministic hash embedder by default; pass a ``[vision]``-backed
        embedder to score real rendered-page images. Query-time only — the graph and
        ``graph.json`` are untouched. When a policy + ``context`` are given, only pages
        whose document is authorized are embedded and scored (§3.2).
        """
        from textgraph.l8_retrieval.vision import HashEmbedder, VisionRetriever

        _nodes, ok_docs = self._auth(context)
        if ok_docs is not None:
            pages = [p for p in self._pages() if p.doc_id in ok_docs]
            retriever = VisionRetriever(pages, embedder or HashEmbedder())
        elif embedder is None:
            if self._vision is None:
                self._vision = VisionRetriever(self._pages(), HashEmbedder())
            retriever = self._vision
        else:
            retriever = VisionRetriever(self._pages(), embedder)
        hits = retriever.search(query, k=k)
        texts = [(h.snippet or h.name) for h in hits]
        kept, truncated = budget_items(hits, texts, max_tokens)
        return SearchResult(query=query, routing="vision", hits=kept, truncated=truncated)

    # -- tool 2: neighbors ------------------------------------------------------

    def neighbors(
        self,
        handle: str,
        *,
        k: int = 20,
        max_tokens: int = 1500,
        context: SecurityContext | None = None,
    ) -> NeighborsResult:
        node_id = self.resolve(handle)
        nodes, ok_docs = self._auth(context)
        if node_id is None or (nodes is not None and node_id not in nodes):
            return NeighborsResult(node_id=handle, name=handle)
        out: list[NeighborEdge] = []
        for e in self._edges:
            if e.predicate in _HIDDEN_NEIGHBORS:
                continue
            if not self._edge_ok(e, nodes, ok_docs):
                continue
            if e.subject == node_id:
                out.append(
                    NeighborEdge(
                        e.predicate,
                        "out",
                        e.object,
                        self._name(e.object),
                        str(e.tag),
                        e.confidence,
                        _citations(e),
                    )
                )
            elif e.object == node_id:
                out.append(
                    NeighborEdge(
                        e.predicate,
                        "in",
                        e.subject,
                        self._name(e.subject),
                        str(e.tag),
                        e.confidence,
                        _citations(e),
                    )
                )
        out.sort(key=lambda n: (-n.confidence, n.predicate, n.other_id))
        texts = [f"{n.predicate} {n.other_name}" for n in out]
        kept, truncated = budget_items(out[:k], texts, max_tokens)
        return NeighborsResult(
            node_id=node_id, name=self._name(node_id), neighbors=kept, truncated=truncated
        )

    # -- tool 3: path -----------------------------------------------------------

    def path(
        self,
        source: str,
        target: str,
        *,
        k: int = 1,
        context: SecurityContext | None = None,
    ) -> PathResult:
        s, t = self.resolve(source), self.resolve(target)
        if s is None or t is None or s == t:
            return PathResult(source=source, target=target)
        nodes, ok_docs = self._auth(context)
        if nodes is not None and (s not in nodes or t not in nodes):
            return PathResult(source=self._name(s), target=self._name(t))
        paths = self._k_shortest(s, t, k, nodes, ok_docs)
        return PathResult(source=self._name(s), target=self._name(t), paths=paths)

    def _edge_weight(self, e: Edge) -> float:
        return -math.log(max(1e-6, min(1.0, e.confidence)))

    def _dijkstra(
        self,
        s: str,
        t: str,
        banned: set[tuple[str, str]],
        blocked: frozenset[str] = frozenset(),
        nodes: frozenset[str] | None = None,
        ok_docs: frozenset[str] | None = None,
    ) -> list[tuple[str, Edge]]:
        """Min ``-log(confidence)`` path as a list of (node, incoming_edge).

        ``banned`` removes specific directed edges and ``blocked`` removes nodes
        entirely — the two exclusions Yen's algorithm needs to enumerate loopless
        alternates. ``nodes``/``ok_docs`` (when set) additionally prune every edge that
        fails the access guard, so a path can never route *through* restricted content.
        """
        dist: dict[str, float] = {s: 0.0}
        prev: dict[str, tuple[str, Edge]] = {}
        pq: list[tuple[float, str]] = [(0.0, s)]
        visited: set[str] = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in visited:
                continue
            visited.add(u)
            if u == t:
                break
            for v, e in sorted(self._rel_adj.get(u, []), key=lambda x: (x[0], x[1].edge_id)):
                if (u, v) in banned or v in visited or v in blocked:
                    continue
                if nodes is not None and not self._edge_ok(e, nodes, ok_docs):
                    continue
                nd = d + self._edge_weight(e)
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = (u, e)
                    heapq.heappush(pq, (nd, v))
        if t not in prev and s != t:
            return []
        chain: list[tuple[str, Edge]] = []
        cur = t
        while cur != s:
            if cur not in prev:
                return []
            pu, pe = prev[cur]
            chain.append((cur, pe))
            cur = pu
        chain.reverse()
        return chain

    def _to_path(self, s: str, chain: list[tuple[str, Edge]]) -> GraphPath:
        node_ids = [s] + [c[0] for c in chain]
        steps: list[PathStep] = []
        likelihood = 1.0
        for e in (c[1] for c in chain):
            steps.append(
                PathStep(
                    self._name(e.subject),
                    e.predicate,
                    self._name(e.object),
                    str(e.tag),
                    e.confidence,
                    _citations(e),
                )
            )
            likelihood *= max(1e-6, min(1.0, e.confidence))
        return GraphPath(
            nodes=[self._name(n) for n in node_ids], steps=steps, likelihood=likelihood
        )

    def _k_shortest(
        self,
        s: str,
        t: str,
        k: int,
        nodes: frozenset[str] | None = None,
        ok_docs: frozenset[str] | None = None,
    ) -> list[GraphPath]:
        """Yen's algorithm over ``-log(confidence)`` weights (bounded, deterministic)."""
        first = self._dijkstra(s, t, set(), nodes=nodes, ok_docs=ok_docs)
        if not first:
            return []
        accepted: list[list[tuple[str, Edge]]] = [first]
        candidates: list[tuple[float, int, list[tuple[str, Edge]]]] = []
        counter = 0
        while len(accepted) < k:
            prev_path = accepted[-1]
            prev_nodes = [s] + [c[0] for c in prev_path]
            for i in range(len(prev_path)):
                spur = prev_nodes[i]
                root = prev_path[:i]
                banned: set[tuple[str, str]] = set()
                for p in accepted:
                    p_nodes = [s] + [c[0] for c in p]
                    if p[:i] == root and i < len(p):
                        banned.add((p_nodes[i], p[i][0]))
                # Block the root's nodes (all before the spur) so the spur path can't
                # loop back through them — this is what makes k-shortest complete.
                blocked = frozenset(prev_nodes[:i])
                spur_chain = self._dijkstra(spur, t, banned, blocked, nodes=nodes, ok_docs=ok_docs)
                if not spur_chain:
                    continue
                total = root + spur_chain
                cost = sum(self._edge_weight(e) for _, e in total)
                node_seq = [s] + [c[0] for c in total]
                if len(set(node_seq)) != len(node_seq):
                    continue  # loopless safety net
                if total in accepted or any(total == c[2] for c in candidates):
                    continue
                counter += 1
                heapq.heappush(candidates, (cost, counter, total))
            if not candidates:
                break
            accepted.append(heapq.heappop(candidates)[2])
        return [self._to_path(s, c) for c in accepted[:k]]

    # -- tool 4: why ------------------------------------------------------------

    def why(
        self,
        handle: str,
        *,
        k: int = 10,
        max_tokens: int = 1500,
        context: SecurityContext | None = None,
    ) -> WhyResult:
        node_id = self.resolve(handle)
        nodes, ok_docs = self._auth(context)
        if node_id is None or (nodes is not None and node_id not in nodes):
            return WhyResult(node_id=handle, name=handle)
        claims = self._claims_about(node_id, nodes)
        # Rationale recorded in the same document(s) the node's claims cite — the
        # "why it was decided" context, scoped to where the node actually appears.
        claim_docs = {c.doc_id for cv in claims for c in cv.citations}
        rationale: list[str] = []
        for n in self._node.values():
            if "Rationale" not in n.labels:
                continue
            node_docs = self._node_docs.get(n.node_id, set())
            if claim_docs and not (node_docs & claim_docs):
                continue
            if ok_docs is not None and not (node_docs & ok_docs):
                continue  # never surface rationale from a document the principal can't read
            rationale.append(self._name(n.node_id))
        rationale = sorted(set(rationale))[:5]
        texts = [f"{c.subject} {c.predicate} {c.object}" for c in claims]
        kept, truncated = budget_items(claims[:k], texts, max_tokens)
        return WhyResult(
            node_id=node_id,
            name=self._name(node_id),
            claims=kept,
            rationale=rationale,
            truncated=truncated,
        )

    def _claims_about(self, node_id: str, nodes: frozenset[str] | None = None) -> list[ClaimView]:
        views: list[ClaimView] = []
        for cid in sorted(self._claim_ids):
            if nodes is not None and cid not in nodes:
                continue  # claim derives only from documents the principal can't read
            p = self._node[cid].properties
            if p.get("subject") == node_id or p.get("object") == node_id:
                cv = self._claim_view(cid)
                if cv:
                    views.append(cv)
        views.sort(key=lambda c: (-c.confidence, c.claim_id))
        return views

    # -- admin inspection (provenance / confidence tier / SAME_AS / invalidation) ----

    def inspect(self, handle: str, *, context: SecurityContext | None = None) -> dict[str, Any]:
        """Full admin detail for one node: provenance, tier, SAME_AS cluster, claim history.

        The "admin console" view (Sprint 4.1): everything an operator needs to audit a node —
        its re-verifiable source spans, the confidence tier(s) of its relations, its
        non-destructive SAME_AS cluster (canonical + members), and each claim's validity
        window / supersession status. Access-controlled like the other tools.
        """
        node_id = self.resolve(handle, context=context)
        nodes, _ok = self._auth(context)
        if node_id is None or (nodes is not None and node_id not in nodes):
            return {"found": False, "node_id": handle, "name": handle}
        n = self._node[node_id]
        p = n.properties

        # SAME_AS cluster (non-destructive): node -> canonical, and canonical -> all members.
        canonical: str | None = None
        for e in self._edges:
            if e.predicate == "SAME_AS" and e.subject == node_id:
                canonical = e.object
        members: list[str] = []
        if canonical is not None:
            members = sorted(
                self._name(e.subject)
                for e in self._edges
                if e.predicate == "SAME_AS" and e.object == canonical
            )

        # Confidence-tier histogram over this node's relation edges (EXTRACTED/INFERRED/…).
        tiers: dict[str, int] = {}
        for e in self._edges:
            if (e.subject == node_id or e.object == node_id) and e.predicate not in _NON_RELATION:
                tiers[str(e.tag)] = tiers.get(str(e.tag), 0) + 1

        claims = self._claims_about(node_id, nodes)
        cit = self._entity_citation.get(node_id)
        return {
            "found": True,
            "node_id": node_id,
            "name": self._name(node_id),
            "labels": list(n.labels),
            "etype": str(p.get("etype", "")),
            "pagerank": round(float(p.get("pagerank", 0.0)), 6),
            "community_label": str(p.get("community_label", "")),
            "provenance": [cit.to_dict()] if cit else [],
            "confidence_tiers": dict(sorted(tiers.items())),
            "same_as": {
                "canonical": self._name(canonical) if canonical else None,
                "members": members,
            },
            "claims": [c.to_dict() for c in claims],
            "superseded_claims": [c.to_dict() for c in claims if c.status == "superseded"],
        }

    # -- tool 5: timeline -------------------------------------------------------

    def timeline(self, handle: str, *, context: SecurityContext | None = None) -> TimelineResult:
        node_id = self.resolve(handle)
        nodes, _ok_docs = self._auth(context)
        if node_id is None or (nodes is not None and node_id not in nodes):
            return TimelineResult(node_id=handle, name=handle)
        events = self._claims_about(node_id, nodes)
        events.sort(key=lambda c: (c.t_valid is None, c.t_valid or "", c.claim_id))
        return TimelineResult(node_id=node_id, name=self._name(node_id), events=events)

    # -- tool 6: contradictions -------------------------------------------------

    def contradictions(self, *, context: SecurityContext | None = None) -> ContradictionsResult:
        nodes, _ok_docs = self._auth(context)
        pairs: list[ContradictionPair] = []
        for e in self._edges:
            if e.predicate != "CONTRADICTS":
                continue
            if nodes is not None and (e.subject not in nodes or e.object not in nodes):
                continue  # never surface a contradiction touching a restricted claim
            a, b = self._claim_view(e.subject), self._claim_view(e.object)
            if a and b:
                pairs.append(ContradictionPair(a, b))
        return ContradictionsResult(pairs=pairs)

    def conflicts(self, *, context: SecurityContext | None = None) -> ConflictsResult:
        """Single-truth conflicts (same subject+predicate, different objects, overlapping).

        Reads the ``Conflict`` nodes built at graph-assembly time and their ``CONTENDS``
        edges. Security-aware: a conflict is hidden unless every contending claim is
        authorized, so it can't leak the existence of a restricted claim.
        """
        nodes, _ok_docs = self._auth(context)
        contenders: dict[str, list[str]] = {}
        for e in self._edges:
            if e.predicate == "CONTENDS" and e.subject.startswith("conflict:"):
                contenders.setdefault(e.subject, []).append(e.object)
        views: list[ConflictView] = []
        for cid in sorted(contenders):
            cnode = self._node.get(cid)
            if cnode is None:
                continue
            claim_ids = sorted(contenders[cid])
            if nodes is not None and any(c not in nodes for c in claim_ids):
                continue  # never surface a conflict touching a restricted claim
            claims = [cv for c in claim_ids if (cv := self._claim_view(c))]
            if len(claims) < 2:
                continue
            p = cnode.properties
            resolved_obj = p.get("resolved_object")
            views.append(
                ConflictView(
                    conflict_id=cid,
                    subject=self._name(str(p.get("subject_id", ""))),
                    predicate=str(p.get("predicate", "")),
                    severity=str(p.get("severity", "")),
                    objects=[self._name(str(o)) for o in p.get("objects", [])],
                    claims=claims,
                    resolution_strategy=str(p.get("resolution_strategy", "")),
                    resolved_object=self._name(str(resolved_obj)) if resolved_obj else None,
                    resolution_note=str(p.get("resolution_note", "")),
                )
            )
        # Most severe first (HIGH < MEDIUM < LOW), then by subject for stable order.
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        views.sort(key=lambda v: (order.get(v.severity, 3), v.subject, v.conflict_id))
        return ConflictsResult(conflicts=views)

    # -- decision provenance: causal chain + similarity -------------------------

    def _resolve_decision(self, handle: str, nodes: frozenset[str] | None) -> str | None:
        """Resolve a decision id or free-text handle to a visible Decision node id."""

        def visible(did: str) -> bool:
            return nodes is None or did in nodes

        if handle in self._decision_ids and visible(handle):
            return handle
        hits = self._decision_bm25.search(handle, k=len(self._decision_ids) or 1)
        for did, _score in hits:
            if visible(did):
                return did
        return None

    def _decision_ref(self, did: str) -> DecisionRef:
        p = self._node[did].properties
        return DecisionRef(
            decision_id=did,
            name=str(p.get("name", did)),
            category=str(p.get("category", "")),
            citations=self._decision_citation.get(did, []),
        )

    def trace_decision_chain(
        self,
        handle: str,
        *,
        max_hops: int = 6,
        max_edges: int = 64,
        context: SecurityContext | None = None,
    ) -> DecisionChainResult:
        """Trace a decision's causal lineage: ancestors (causes) and descendants (effects).

        Walks ``CAUSED`` / ``INFLUENCED`` / ``PRECEDENT_FOR`` edges — backward for what led
        to the decision, forward for what it led to — as ordered, cited hops. Cycle-safe and
        bounded (``max_hops`` depth, ``max_edges`` total) so cost stays auditable (G7).
        """
        nodes, _ok_docs = self._auth(context)
        did = self._resolve_decision(handle, nodes)
        if did is None:
            return DecisionChainResult(found=False)

        def walk(
            adj: dict[str, list[tuple[str, Edge]]], forward: bool
        ) -> tuple[list[ChainHop], bool]:
            hops: list[ChainHop] = []
            seen = {did}
            frontier = [(did, 0)]
            truncated = False
            while frontier:
                node_id, depth = frontier.pop(0)
                if depth >= max_hops:
                    continue
                # Deterministic order: by (relation, other name, edge id).
                for other, e in sorted(
                    adj.get(node_id, []),
                    key=lambda pair: (pair[1].predicate, self._name(pair[0]), pair[1].edge_id),
                ):
                    if nodes is not None and other not in nodes:
                        continue  # never surface a hop into a restricted decision
                    if len(hops) >= max_edges:
                        truncated = True
                        break
                    cause, effect = (other, node_id) if not forward else (node_id, other)
                    hops.append(
                        ChainHop(
                            relation=e.predicate,
                            from_id=cause,
                            from_name=self._name(cause),
                            to_id=effect,
                            to_name=self._name(effect),
                            depth=depth + 1,
                            citations=_citations(e),
                        )
                    )
                    if other not in seen:
                        seen.add(other)
                        frontier.append((other, depth + 1))
                if len(hops) >= max_edges:
                    truncated = True
                    break
            return hops, truncated

        ancestors, trunc_a = walk(self._causal_in, forward=False)
        descendants, trunc_d = walk(self._causal_out, forward=True)
        return DecisionChainResult(
            found=True,
            decision=self._decision_ref(did),
            ancestors=ancestors,
            descendants=descendants,
            truncated=trunc_a or trunc_d,
        )

    def find_similar_decisions(
        self, query: str, *, k: int = 5, context: SecurityContext | None = None
    ) -> SimilarDecisionsResult:
        """Rank Decision nodes by BM25 relevance of their statement text to ``query``.

        Every hit is cited to the span the decision was derived from. Security-aware: a
        decision whose source document is unauthorized never surfaces.
        """
        nodes, _ok_docs = self._auth(context)
        ranked = self._decision_bm25.search(query, k=max(k * 2, k))
        hits: list[DecisionHit] = []
        for did, score in ranked:
            if nodes is not None and did not in nodes:
                continue
            p = self._node[did].properties
            hits.append(
                DecisionHit(
                    decision_id=did,
                    name=str(p.get("name", did)),
                    category=str(p.get("category", "")),
                    score=score,
                    citations=self._decision_citation.get(did, []),
                )
            )
        truncated = len(hits) > k
        return SimilarDecisionsResult(query=query, hits=hits[:k], truncated=truncated)

    # -- tool 7: communities ----------------------------------------------------

    def communities(
        self, *, top_members: int = 8, context: SecurityContext | None = None
    ) -> CommunitiesResult:
        nodes, _ok_docs = self._auth(context)
        buckets: dict[int, list[str]] = {}
        labels: dict[int, str] = {}
        for nid in sorted(self._entity_ids):
            if nodes is not None and nid not in nodes:
                continue  # community rosters/sizes are computed over authorized members only
            p = self._node[nid].properties
            cid = p.get("community")
            if cid is None:
                continue
            cid = int(cid)
            buckets.setdefault(cid, []).append(nid)
            labels[cid] = str(p.get("community_label", ""))
        views: list[CommunityView] = []
        for cid in sorted(buckets):
            members = sorted(
                buckets[cid],
                key=lambda nid: (-float(self._node[nid].properties.get("pagerank", 0.0)), nid),
            )
            views.append(
                CommunityView(
                    community_id=cid,
                    label=labels.get(cid, ""),
                    size=len(members),
                    members=[self._name(m) for m in members[:top_members]],
                )
            )
        return CommunitiesResult(communities=views)

    # -- tool 8: stats ----------------------------------------------------------

    def stats(self, *, top_k: int = 10, context: SecurityContext | None = None) -> StatsResult:
        # Security-scoped (Phase 9): under a policy, counts and — critically — the named
        # top_entities are computed over authorized content only, so stats can't leak the
        # name of a restricted (e.g. high-PageRank) entity to an unauthorized principal.
        nodes, ok_docs = self._auth(context)

        def visible(nid: str) -> bool:
            return nodes is None or nid in nodes

        label_counts: dict[str, int] = {}
        node_total = 0
        for nid, n in self._node.items():
            if not visible(nid):
                continue
            node_total += 1
            for label in n.labels:
                label_counts[label] = label_counts.get(label, 0) + 1
        pred_counts: dict[str, int] = {}
        edge_total = 0
        for e in self._edges:
            if nodes is not None and not self._edge_ok(e, nodes, ok_docs):
                continue
            edge_total += 1
            pred_counts[e.predicate] = pred_counts.get(e.predicate, 0) + 1
        entities = [nid for nid in self._entity_ids if visible(nid)]
        counts = {
            "nodes": node_total,
            "edges": edge_total,
            "entities": len(entities),
            "chunks": sum(1 for nid in self._chunk_ids if visible(nid)),
            "claims": sum(1 for nid in self._claim_ids if visible(nid)),
            **{f"label:{k}": v for k, v in sorted(label_counts.items())},
            **{f"predicate:{k}": v for k, v in sorted(pred_counts.items())},
        }
        top = sorted(
            entities,
            key=lambda nid: (-float(self._node[nid].properties.get("pagerank", 0.0)), nid),
        )[:top_k]
        top_entities = [
            {
                "node_id": nid,
                "name": self._name(nid),
                "pagerank": round(float(self._node[nid].properties.get("pagerank", 0.0)), 6),
                "community_label": str(self._node[nid].properties.get("community_label", "")),
            }
            for nid in top
        ]
        return StatsResult(counts=counts, top_entities=top_entities)


def engine_from_path(root: str, *, config: object | None = None) -> QueryEngine:
    """Build a graph from a corpus path and return a ready QueryEngine."""
    from textgraph.core.config import Config
    from textgraph.pipeline import build

    result = build(root, config=config if isinstance(config, Config) else None)
    return QueryEngine(result.nodes, result.edges)
