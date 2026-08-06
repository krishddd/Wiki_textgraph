"""Extraction-quality benchmark — entity/edge correctness, citations, cost (Sprint 3.1).

"No number without its cost" (G7), and no *quality* claim without a gold set. This measures
how correct the extracted graph is against a hand-labelled gold annotation of the in-repo
`docs` fixture — honestly, including the **false / hallucinated edge rate** and the one
coreference error the deterministic extractor still makes. It is deterministic for every
correctness metric (counts), with wall-clock latency reported separately.

Metrics:
  * **Entity precision / recall / F1** — extracted entity names vs gold.
  * **Edge precision / recall / F1** — *asserted* (positive-polarity) relation triples vs
    gold. Negated relations ("did not transfer") are excluded because the extractor tags
    them `polarity=neg` — crediting it for correctly *not* asserting them.
  * **False (hallucinated) edge rate** — asserted triples not in gold / asserted triples.
  * **Citation coverage** — fraction of asserted relation edges carrying a source span.
    (Byte-level re-verification of those spans is separately gated at 100% by
    `tests/integration/test_edge_provenance.py`.)
  * **Cost** — node/edge counts (deterministic) + build latency (machine-dependent).

Usage:
    python -m benchmarks.quality           # print the report
    python -m benchmarks.quality --write     # also append the block to BENCHMARKS.md
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from textgraph.pipeline import build

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "corpora" / "docs"

_RELATION_PREDS = frozenset(
    {"TRANSFERRED", "CONTROLS", "BENEFICIAL_OWNER_OF", "DIRECTOR_OF", "ASSOCIATED_WITH"}
)

# Hand-labelled gold for the `docs` fixture.
GOLD_ENTITIES = {
    "Acme Corp",
    "Beta Ltd",
    "Gamma Holdings",
    "Delta Trust",
    "Omega Bank",
    "Sigma Partners",
    "John Doe",
    "$2,000,000",
    "2026-07-30",
}
GOLD_RELATIONS = {
    ("Acme Corp", "TRANSFERRED", "Beta Ltd"),
    ("Acme Corp", "CONTROLS", "Gamma Holdings"),
    ("Gamma Holdings", "BENEFICIAL_OWNER_OF", "Delta Trust"),
    ("John Doe", "DIRECTOR_OF", "Beta Ltd"),
    ("Acme Corp", "ASSOCIATED_WITH", "Sigma Partners"),
    (
        "Acme Corp",
        "TRANSFERRED",
        "Gamma Holdings",
    ),  # "the company then transferred to Gamma" = Acme
}


def _prf(pred: set, gold: set) -> tuple[float, float, float]:
    tp = len(pred & gold)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return round(precision, 3), round(recall, 3), round(f1, 3)


def measure() -> dict[str, object]:
    t0 = time.perf_counter()
    result = build(FIXTURE)
    latency_ms = (time.perf_counter() - t0) * 1000
    name = {n.node_id: str(n.properties.get("name", "")) for n in result.nodes}

    entities = {name[n.node_id] for n in result.nodes if "Entity" in n.labels}
    rels: set[tuple[str, str, str]] = set()
    cited = 0
    for e in result.edges:
        if e.predicate not in _RELATION_PREDS:
            continue
        if not (e.subject.startswith("entity:") and e.object.startswith("entity:")):
            continue
        if str(e.properties.get("polarity", "pos")) == "neg":
            continue  # correctly-negated relation is not an asserted edge
        rels.add((name[e.subject], e.predicate, name[e.object]))
        if e.source_spans:
            cited += 1

    ep, er, ef = _prf(entities, GOLD_ENTITIES)
    rp, rr, rf = _prf(rels, GOLD_RELATIONS)
    asserted = len(rels)
    false_edges = len(rels - GOLD_RELATIONS)
    return {
        "entity_prf": (ep, er, ef),
        "edge_prf": (rp, rr, rf),
        "asserted_edges": asserted,
        "false_edge_rate": round(false_edges / asserted, 3) if asserted else 0.0,
        "false_edges": sorted(rels - GOLD_RELATIONS),
        "missed_edges": sorted(GOLD_RELATIONS - rels),
        "citation_coverage": round(cited / asserted, 3) if asserted else 0.0,
        "nodes": len(result.nodes),
        "edges": len(result.edges),
        "latency_ms": round(latency_ms, 1),
    }


def run() -> str:
    m = measure()
    ep, er, ef = m["entity_prf"]  # type: ignore[misc]
    rp, rr, rf = m["edge_prf"]  # type: ignore[misc]
    lines = [
        "## Extraction quality (Phase 3.1) - vs a hand-labelled gold set",
        "",
        f"Fixture: `tests/fixtures/corpora/docs`, deterministic rules extractor. "
        f"{m['nodes']} nodes / {m['edges']} edges, build {m['latency_ms']} ms.",
        "",
        "| Metric | Precision | Recall | F1 |",
        "|---|---|---|---|",
        f"| Entities | {ep} | {er} | {ef} |",
        f"| Asserted relations | {rp} | {rr} | {rf} |",
        "",
        f"- **False / hallucinated edge rate: {m['false_edge_rate']}** "
        f"({len(m['false_edges'])} of {m['asserted_edges']} asserted edges).",
        f"- **Citation coverage: {m['citation_coverage']}** (byte-level re-verification of those "
        "spans is gated at 100% by `test_edge_provenance`).",
        "- Negated relations are correctly tagged `polarity=neg` and excluded from asserted edges.",
        f"- Honest weakness - false edge(s): {m['false_edges'] or 'none'}; "
        f"missed: {m['missed_edges'] or 'none'} (a coreference limit of the rules backend).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extraction-quality benchmark")
    parser.add_argument("--write", action="store_true", help="append the block to BENCHMARKS.md")
    args = parser.parse_args(argv)
    report = run()
    print(report)
    if args.write:
        path = REPO / "BENCHMARKS.md"
        prior = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(prior.rstrip() + "\n\n" + report, encoding="utf-8")
        print(f"(appended to {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
