"""Artifact writer (L9): emit the full textgraph-out/ directory.

Produces graph.json (the agent's byte-stable contract), GRAPH_REPORT.md,
graph.html, schema.yaml (observed labels/predicates), and manifest.json (per-stage
accounting, G7). graph.json is the only byte-gated artifact (determinism CI).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from textgraph import __version__
from textgraph.core.canonical_json import canonical_dump_bytes
from textgraph.core.layout import IngestResult
from textgraph.l9_artifacts import analytics_lite
from textgraph.l9_artifacts.graph_html import build_html
from textgraph.l9_artifacts.graph_json import build_graph_document, dump_graph_bytes
from textgraph.l9_artifacts.report import render_report
from textgraph.store.base import Edge, Node


@dataclass
class ArtifactPaths:
    out_dir: Path
    graph_json: Path
    report: Path
    graph_html: Path
    schema_yaml: Path
    manifest: Path


def _schema_yaml(nodes: list[Node], edges: list[Edge]) -> str:
    entity_types = sorted({label for n in nodes for label in n.labels})
    relation_types = sorted({e.predicate for e in edges})
    doc = {
        "version": 0,
        # Observed from L1 structure + L3 IE; induced/user-supplied ontology is Phase 3.
        "mode": "observed",
        "entity_types": entity_types,
        "relation_types": relation_types,
    }
    return yaml.safe_dump(doc, sort_keys=True, allow_unicode=True)


def _manifest(
    *,
    config_hash: str,
    results: list[IngestResult],
    nodes: list[Node],
    edges: list[Edge],
    timings_ms: dict[str, float] | None,
    ie_stats: dict[str, int] | None,
    er_stats: dict[str, int] | None,
) -> dict[str, Any]:
    timings_ms = timings_ms or {}
    ie_stats = ie_stats or {}
    er_stats = er_stats or {}
    tag_counts = Counter(str(e.tag) for e in edges)
    entity_nodes = sum(1 for n in nodes if "Entity" in n.labels and "Canonical" not in n.labels)
    pron_total = ie_stats.get("pronouns_total", 0)
    pron_resolved = ie_stats.get("pronouns_resolved", 0)
    coref_coverage = round(pron_resolved / pron_total, 4) if pron_total else 0.0
    return {
        "tool_version": __version__,
        "config_hash": config_hash,
        "llm_enabled": False,
        "stages": [
            {
                "layer": "L0",
                "wall_ms": round(timings_ms.get("L0", 0.0), 3),
                "nodes_out": 0,
                "edges_out": 0,
                "model": None,
            },
            {
                "layer": "L1",
                "wall_ms": round(timings_ms.get("L1", 0.0), 3),
                "nodes_out": len(nodes) - entity_nodes,
                "edges_out": 0,
                "model": None,
            },
            {
                "layer": "L2",
                "wall_ms": 0.0,
                "nodes_out": 0,
                "edges_out": 0,
                "model": "coref-lite (rules)",
            },
            {
                "layer": "L3",
                "wall_ms": round(timings_ms.get("L2_L3", 0.0), 3),
                "nodes_out": entity_nodes,
                "edges_out": ie_stats.get("relations", 0),
                "model": "rules",
            },
            {
                "layer": "L5",
                "wall_ms": round(timings_ms.get("L5", 0.0), 3),
                "nodes_out": er_stats.get("canonical_entities", 0),
                "edges_out": er_stats.get("same_as_edges", 0),
                "model": "rules",
            },
        ],
        "coverage": {
            "doc_count": len(results),
            "total_raw_bytes": sum(ir.canonical.raw_len for ir in results),
            "tag_counts": dict(sorted(tag_counts.items())),
            "entities": entity_nodes,
            "relations": ie_stats.get("relations", 0),
            "coref_coverage": coref_coverage,
            "coref_pronouns": {"total": pron_total, "resolved": pron_resolved},
            "canonical_entities": er_stats.get("canonical_entities", 0),
            "same_as_edges": er_stats.get("same_as_edges", 0),
            "blocking_candidate_pairs": er_stats.get("candidate_pairs", 0),
            "blocking_cross_product": er_stats.get("cross_product", 0),
        },
    }


def write_artifacts(
    out_dir: str | Path,
    *,
    config_hash: str,
    results: list[IngestResult],
    nodes: list[Node],
    edges: list[Edge],
    timings_ms: dict[str, float] | None = None,
    ie_stats: dict[str, int] | None = None,
    er_stats: dict[str, int] | None = None,
) -> ArtifactPaths:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    diag = analytics_lite.compute(nodes, edges)

    graph_doc = build_graph_document(
        config_hash=config_hash, results=results, nodes=nodes, edges=edges
    )
    paths = ArtifactPaths(
        out_dir=out,
        graph_json=out / "graph.json",
        report=out / "GRAPH_REPORT.md",
        graph_html=out / "graph.html",
        schema_yaml=out / "schema.yaml",
        manifest=out / "manifest.json",
    )
    paths.graph_json.write_bytes(dump_graph_bytes(graph_doc))
    paths.report.write_text(
        render_report(
            results=results, nodes=nodes, edges=edges, diag=diag, config_hash=config_hash
        ),
        encoding="utf-8",
    )
    paths.graph_html.write_text(
        build_html(results=results, nodes=nodes, edges=edges, diag=diag, config_hash=config_hash),
        encoding="utf-8",
    )
    paths.schema_yaml.write_text(_schema_yaml(nodes, edges), encoding="utf-8")
    paths.manifest.write_bytes(
        canonical_dump_bytes(
            _manifest(
                config_hash=config_hash,
                results=results,
                nodes=nodes,
                edges=edges,
                timings_ms=timings_ms,
                ie_stats=ie_stats,
                er_stats=er_stats,
            )
        )
    )
    return paths
