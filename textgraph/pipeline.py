"""TextGraph build pipeline (Phase 1: L0 + L1).

Runs deterministic ingestion (L0) and zero-model structure parsing (L1) over a
corpus, assembles an in-memory graph, and produces the L9 artifacts. Each later
phase slots a real layer in without changing this orchestration or breaking the
byte-identical guarantee (G1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.incremental import DocIECache
from textgraph.core.layout import IngestResult
from textgraph.l0_ingest import ingest_path
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l1_structure import parse_corpus
from textgraph.l1_structure.decisions import derive_decisions
from textgraph.l3_encoder_ie import emit_ie, run_ie
from textgraph.l5_entity_resolution import build_records, emit_er, run_er
from textgraph.l6_graph_model import apply_temporal, reify_claims
from textgraph.l6_graph_model.conflicts import detect_conflicts, resolve_conflicts
from textgraph.l7_analytics import Analytics, compute_analytics
from textgraph.l7_analytics.enrich import contradiction_edges, enrich_nodes
from textgraph.l8_retrieval.emit_chunks import emit_chunks
from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes
from textgraph.store.base import Edge, Node, SourceSpan
from textgraph.store.memory import InMemoryGraphStore

# Extensions we attempt to ingest. Everything else is skipped so a corpus dir can
# sit next to binaries without polluting the graph. Unknown *text* extensions can
# still be ingested explicitly via the L0 API.
_INGEST_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".mdx",
        ".txt",
        ".text",
        ".log",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".chat",
        ".transcript",
        # Rich documents (investigator formats: filings, memos, reports, exports).
        ".html",
        ".htm",
        ".xhtml",
        ".docx",
        ".odt",
        ".rtf",
        ".epub",
        ".pdf",
    }
)


@dataclass
class BuildResult:
    config: Config
    results: list[IngestResult]
    store: InMemoryGraphStore
    nodes: list[Node]
    edges: list[Edge]
    timings_ms: dict[str, float] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    ie_stats: dict[str, int] = field(default_factory=dict)
    er_stats: dict[str, int] = field(default_factory=dict)
    graph_stats: dict[str, int] = field(default_factory=dict)
    analytics: Analytics | None = None

    @property
    def config_hash(self) -> str:
        return self.config.config_hash()


def _iter_corpus_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _INGEST_EXTENSIONS
    )


def _run_l4(
    nodes: list[Node],
    edges: list[Edge],
    analytics: Analytics,
    config: Config,
    cache_dir: str | Path | None,
) -> tuple[list[Node], list[Edge]]:
    """Resolve the LLM client + cache and run L4 synthesis; return ([], []) if skipped."""
    import tempfile

    from textgraph.l4_llm_optional import PromptCache, resolve_client, synthesize

    client = resolve_client(config)
    if client is None:
        return [], []
    llm_cache_dir = (
        Path(cache_dir) / "llm"
        if cache_dir is not None
        else Path(tempfile.mkdtemp(prefix="textgraph-llm-"))
    )
    cache = PromptCache(llm_cache_dir)
    return synthesize(nodes, edges, analytics, client, cache, max_calls=config.llm_max_calls)


def _run_llm_extract(
    nodes: list[Node],
    edges: list[Edge],
    config: Config,
    cache_dir: str | Path | None,
) -> tuple[list[Node], list[Edge]]:
    """Resolve the LLM client + cache and run GENERATED relation extraction; ([], []) if skipped."""
    import tempfile

    from textgraph.l4_llm_optional import PromptCache, resolve_client
    from textgraph.l4_llm_optional.extract import extract_llm_relations

    client = resolve_client(config)
    if client is None:
        return [], []
    llm_cache_dir = (
        Path(cache_dir) / "llm"
        if cache_dir is not None
        else Path(tempfile.mkdtemp(prefix="textgraph-llm-"))
    )
    cache = PromptCache(llm_cache_dir)
    # Chunk text + the span it cites (from its incoming CONTAINS edge), for coarse provenance.
    chunk_ids = {n.node_id for n in nodes if "Chunk" in n.labels}
    by_id = {n.node_id: n for n in nodes}
    chunk_span: dict[str, SourceSpan] = {}
    for e in edges:
        if e.object in chunk_ids and e.source_spans:
            chunk_span.setdefault(e.object, e.source_spans[0])
    chunks = [
        (cid, str(by_id[cid].properties.get("text", "")), chunk_span[cid])
        for cid in sorted(chunk_ids)
        if cid in chunk_span
    ]
    return extract_llm_relations(chunks, client, cache, max_calls=config.llm_extract_max_calls)


def build(
    root: str | Path, *, config: Config | None = None, cache_dir: str | Path | None = None
) -> BuildResult:
    """Run the full pipeline over a corpus path and return the assembled graph.

    ``cache_dir`` enables incremental rebuilds (G5): per-document IE is cached by
    ``(doc_id, config_hash)``, so editing one file only re-extracts that file. The
    output is byte-identical to a full build.
    """
    config = config or Config()
    root = Path(root)
    cache = DocIECache(cache_dir) if cache_dir is not None else None
    config_hash = config.config_hash()

    results: list[IngestResult] = []
    skipped: list[str] = []
    t0 = time.perf_counter()
    for p in _iter_corpus_files(root):
        try:
            results.append(ingest_path(p))
        except UnsupportedFormat as exc:
            skipped.append(f"{p.name}: {exc}")
    l0_ms = (time.perf_counter() - t0) * 1000

    # L1 — deterministic structural spine.
    t1 = time.perf_counter()
    nodes, edges = parse_corpus(results)
    l1_ms = (time.perf_counter() - t1) * 1000

    # Decision provenance — promote decision-worthy Rationale markers into first-class
    # Decision nodes + causal edges. Pure function of the L1 spine; no downstream deps.
    decision_count = 0
    if config.derive_decisions:
        dec_nodes, dec_edges = derive_decisions(nodes, edges)
        decision_count = len(dec_nodes)
        nodes = sorted(
            ({n.node_id: n for n in nodes} | {n.node_id: n for n in dec_nodes}).values(),
            key=lambda n: n.node_id,
        )
        edges = sorted(
            ({e.edge_id: e for e in edges} | {e.edge_id: e for e in dec_edges}).values(),
            key=lambda e: e.edge_id,
        )

    # L2 + L3 — encoder IE (default: deterministic rule backend). Entities merge
    # across documents by (type, normalized name); relations/mentions carry spans.
    entity_nodes: dict[str, Node] = {}
    ie_edges: dict[str, Edge] = {}
    ie_ms = 0.0
    pron_total = pron_resolved = entity_count = relation_count = 0
    if config.extract_ie:
        t2 = time.perf_counter()
        for ir in results:
            cached = cache.get(ir.doc_id, config_hash) if cache else None
            if cached is not None:
                ie_n = cached["nodes"]
                ie_e = cached["edges"]
                pron_total += int(cached["pronouns_total"])
                pron_resolved += int(cached["pronouns_resolved"])
                relation_count += int(cached["relations"])
            else:
                ie = run_ie(
                    ir.text, blocks=ir.blocks, backend=config.ie_backend, onnx=config.ie_onnx
                )
                pron_total += ie.pronouns_total
                pron_resolved += ie.pronouns_resolved
                relation_count += len(ie.relations)
                ie_n, ie_e = emit_ie(ir, ie)
                if cache:
                    cache.put(
                        ir.doc_id,
                        config_hash,
                        ie_n,
                        ie_e,
                        pronouns_total=ie.pronouns_total,
                        pronouns_resolved=ie.pronouns_resolved,
                        relations=len(ie.relations),
                    )
            for n in ie_n:
                existing = entity_nodes.get(n.node_id)
                if existing is None:
                    entity_nodes[n.node_id] = n
                else:
                    # Same entity in multiple docs: accumulate the total mention count
                    # so the node reflects corpus-wide evidence, not just the first doc.
                    existing.properties["mention_count"] = int(
                        existing.properties.get("mention_count", 0)
                    ) + int(n.properties.get("mention_count", 0))
            for e in ie_e:
                ie_edges.setdefault(e.edge_id, e)
        entity_count = len(entity_nodes)
        ie_ms = (time.perf_counter() - t2) * 1000

    merged_nodes = {n.node_id: n for n in nodes} | entity_nodes
    merged_edges = {e.edge_id: e for e in edges} | ie_edges
    nodes = sorted(merged_nodes.values(), key=lambda n: n.node_id)
    edges = sorted(merged_edges.values(), key=lambda e: e.edge_id)

    # L5 — entity resolution: link alias entities to canonical nodes via SAME_AS.
    er_ms = 0.0
    er_stats: dict[str, int] = {}
    if config.resolve_entities and config.extract_ie:
        t3 = time.perf_counter()
        records = build_records(nodes, edges)
        er = run_er(records, backend=config.er_backend)
        er_nodes, er_edges = emit_er(er)
        merged_nodes = {n.node_id: n for n in nodes} | {n.node_id: n for n in er_nodes}
        merged_edges = {e.edge_id: e for e in edges} | {e.edge_id: e for e in er_edges}
        nodes = sorted(merged_nodes.values(), key=lambda n: n.node_id)
        edges = sorted(merged_edges.values(), key=lambda e: e.edge_id)
        er_ms = (time.perf_counter() - t3) * 1000
        er_stats = {
            "canonical_entities": len(er.clusters),
            "same_as_edges": len(er.same_as),
            "candidate_pairs": er.candidate_pairs,
            "cross_product": er.cross_product,
        }

    # L6 — reify relation edges into citable Claim nodes (keeps the direct edges),
    # then close validity windows across contradicting claims (invalidation, G8).
    l6_ms = 0.0
    claim_count = 0
    supersedes_count = 0
    if config.reify_claims and config.extract_ie:
        t4 = time.perf_counter()
        claim_nodes, claim_edges = reify_claims(nodes, edges)
        claim_count = len(claim_nodes)
        if config.invalidate_claims:
            claim_nodes, supersedes_edges = apply_temporal(claim_nodes, claim_edges)
            supersedes_count = len(supersedes_edges)
            claim_edges = sorted(
                (
                    {e.edge_id: e for e in claim_edges} | {e.edge_id: e for e in supersedes_edges}
                ).values(),
                key=lambda e: e.edge_id,
            )
        nodes = sorted(
            ({n.node_id: n for n in nodes} | {n.node_id: n for n in claim_nodes}).values(),
            key=lambda n: n.node_id,
        )
        edges = sorted(
            ({e.edge_id: e for e in edges} | {e.edge_id: e for e in claim_edges}).values(),
            key=lambda e: e.edge_id,
        )
        l6_ms = (time.perf_counter() - t4) * 1000

    # Conflict detection — surface single-truth disagreements (Acme controls Beta vs Gamma)
    # as first-class Conflict nodes. Never silently merges; resolution is a separate,
    # opt-in step. Needs claims (L6) + SAME_AS (L5) + validity windows (invalidation).
    conflict_count = 0
    if config.detect_conflicts and config.reify_claims and config.extract_ie:
        conflict_nodes, conflict_edges = detect_conflicts(
            nodes, edges, single_truth=config.single_truth_predicates
        )
        conflict_count = len(conflict_nodes)
        nodes = sorted(
            ({n.node_id: n for n in nodes} | {n.node_id: n for n in conflict_nodes}).values(),
            key=lambda n: n.node_id,
        )
        edges = sorted(
            ({e.edge_id: e for e in edges} | {e.edge_id: e for e in conflict_edges}).values(),
            key=lambda e: e.edge_id,
        )
        # Opt-in resolution (never silent): pick a winner per conflict and demote losing
        # claims non-destructively. Off unless a strategy is configured.
        if conflict_count and config.resolve_conflicts_strategy:
            credibility = {
                ir.doc_id: config.source_credibility[ir.source_name]
                for ir in results
                if ir.source_name in config.source_credibility
            }
            resolved_nodes, resolved_edges = resolve_conflicts(
                nodes,
                edges,
                strategy=config.resolve_conflicts_strategy,
                credibility_by_doc=credibility,
            )
            nodes = sorted(
                ({n.node_id: n for n in nodes} | {n.node_id: n for n in resolved_nodes}).values(),
                key=lambda n: n.node_id,
            )
            edges = sorted(
                ({e.edge_id: e for e in edges} | {e.edge_id: e for e in resolved_edges}).values(),
                key=lambda e: e.edge_id,
            )

    # L7 — graph analytics folded back into the graph (node props + CONTRADICTS).
    l7_ms = 0.0
    analytics: Analytics | None = None
    community_count = 0
    contradiction_count = 0
    if config.analytics:
        t5 = time.perf_counter()
        analytics = compute_analytics(nodes, edges, backend=config.analytics_backend)
        nodes = sorted(enrich_nodes(nodes, analytics), key=lambda n: n.node_id)
        claim_ids = {n.node_id for n in nodes if "Claim" in n.labels}
        contra = contradiction_edges(edges, analytics, claim_ids)
        contradiction_count = len(contra)
        edges = sorted(
            ({e.edge_id: e for e in edges} | {e.edge_id: e for e in contra}).values(),
            key=lambda e: e.edge_id,
        )
        community_count = len(analytics.community_labels)
        l7_ms = (time.perf_counter() - t5) * 1000

    # L8 — dual-node retrieval graph: emit Chunk nodes + entity<->chunk links.
    l8_ms = 0.0
    chunk_count = 0
    if config.emit_chunks:
        t6 = time.perf_counter()
        chunk_nodes, chunk_edges = emit_chunks(results, nodes, edges)
        chunk_count = len(chunk_nodes)
        nodes = sorted(
            ({n.node_id: n for n in nodes} | {n.node_id: n for n in chunk_nodes}).values(),
            key=lambda n: n.node_id,
        )
        edges = sorted(
            ({e.edge_id: e for e in edges} | {e.edge_id: e for e in chunk_edges}).values(),
            key=lambda e: e.edge_id,
        )
        l8_ms = (time.perf_counter() - t6) * 1000

    # LLM relation enrichment (opt-in, GENERATED). Runs the LLM over chunks to add relations
    # the deterministic extractors missed; quarantined by tag, bounded by budget (G7). Gated
    # on `llm_extract` alone (independent of `llm_enabled`, which drives L4 summaries) so
    # `--llm-extract` adds only extraction relations — not community summaries.
    gen_relation_count = 0
    if config.llm_extract and config.emit_chunks:
        gen_nodes, gen_edges = _run_llm_extract(nodes, edges, config, cache_dir)
        gen_relation_count = len(gen_edges)
        if gen_edges:
            nodes = sorted(
                ({n.node_id: n for n in nodes} | {n.node_id: n for n in gen_nodes}).values(),
                key=lambda n: n.node_id,
            )
            edges = sorted(
                ({e.edge_id: e for e in edges} | {e.edge_id: e for e in gen_edges}).values(),
                key=lambda e: e.edge_id,
            )

    # L4 — optional LLM synthesis (opt-in, GENERATED-tagged, quarantined). Runs last so
    # it can summarize the finished communities; skipped (never fails) if unconfigured.
    l4_ms = 0.0
    summary_count = 0
    if config.llm_enabled and analytics is not None:
        t7 = time.perf_counter()
        summary_nodes, summary_edges = _run_l4(nodes, edges, analytics, config, cache_dir)
        summary_count = len(summary_nodes)
        if summary_nodes:
            nodes = sorted(
                ({n.node_id: n for n in nodes} | {n.node_id: n for n in summary_nodes}).values(),
                key=lambda n: n.node_id,
            )
            edges = sorted(
                ({e.edge_id: e for e in edges} | {e.edge_id: e for e in summary_edges}).values(),
                key=lambda e: e.edge_id,
            )
        l4_ms = (time.perf_counter() - t7) * 1000

    store = InMemoryGraphStore()
    for n in nodes:
        store.add_node(n)
    for e in edges:
        store.add_edge(e)

    return BuildResult(
        config=config,
        results=results,
        store=store,
        nodes=nodes,
        edges=edges,
        timings_ms={
            "L0": l0_ms,
            "L1": l1_ms,
            "L2_L3": ie_ms,
            "L4": l4_ms,
            "L5": er_ms,
            "L6": l6_ms,
            "L7": l7_ms,
            "L8": l8_ms,
        },
        skipped=skipped,
        ie_stats={
            "entities": entity_count,
            "relations": relation_count,
            "pronouns_total": pron_total,
            "pronouns_resolved": pron_resolved,
        },
        er_stats=er_stats,
        graph_stats={
            "decisions": decision_count,
            "claims": claim_count,
            "conflicts": conflict_count,
            "supersedes": supersedes_count,
            "communities": community_count,
            "contradictions": contradiction_count,
            "chunks": chunk_count,
            "summaries": summary_count,
            "llm_relations": gen_relation_count,
        },
        analytics=analytics,
    )


def build_graph(root: str | Path, *, config: Config | None = None) -> dict[str, object]:
    """Build and return the graph.json document (dict)."""
    result = build(root, config=config)
    return build_graph_document(
        config_hash=result.config_hash,
        results=result.results,
        nodes=result.nodes,
        edges=result.edges,
    )


def build_graph_bytes(root: str | Path, *, config: Config | None = None) -> bytes:
    """Return the canonical-JSON bytes of graph.json (what lands on disk)."""
    return dump_graph_bytes(build_graph(root, config=config))
