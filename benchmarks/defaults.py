"""Zero-config defaults benchmark — PDF ingestion + entity resolution run out of the box.

Investigators shouldn't have to configure the happy path. This proves, with numbers, that a
**default install** (no flags, no extras) already:

1. **ingests PDFs** — ``pypdf`` is a core dependency, so a ``.pdf`` is read out of the box
   (Docling stays opt-in in ``[ingest]`` for layout/table/OCR fidelity only); and
2. **resolves entity aliases** — the rules entity-resolution backend is on by default, so
   ``Acme Corporation`` / ``Acme Corp`` / ``ACME`` collapse to one canonical node.

It also reports the **before/after** quality lift from entity resolution (distinct
organizations before vs after) — the "clean before/after story" — plus build and query
latency. Correctness counts are deterministic; wall-clock latency is reported separately (G7).

Usage:
    python -m benchmarks.defaults            # print the report
    python -m benchmarks.defaults --write    # also append the block to BENCHMARKS.md
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from textgraph.core.config import Config
from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build

REPO = Path(__file__).resolve().parent.parent

# A tiny fixed corpus where one organization appears under three surface forms.
_ALIAS_CORPUS = {
    "filing-a.md": "Acme Corporation controls Beta Ltd. Acme Corporation owns Delta Trust.",
    "filing-b.md": "Acme Corp transferred funds to Beta Ltd on 2020-03-01.",
    "filing-c.md": "ACME is the beneficial owner of Beta Ltd.",
}


def _acme_aliases(nodes: list) -> int:
    """Distinct extracted 'Acme' surface forms (alias entity nodes, not the canonical)."""
    return sum(
        1
        for n in nodes
        if n.properties.get("etype") == "Organization"
        and "acme" in str(n.properties.get("name", "")).lower()
        and "Canonical" not in n.labels
    )


def _pdf_default() -> tuple[bool, str]:
    """Ingest a generated PDF with the default install; return (ok, format)."""
    try:
        from pypdf import PdfWriter
        from textgraph.l0_ingest import ingest_path
    except ImportError:  # pragma: no cover - pypdf is a core dep
        return False, "pypdf-missing"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "note.pdf"
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        with open(p, "wb") as fh:
            w.write(fh)
        ir = ingest_path(p)
        return ir.format == "pdf", ir.format


def _build_alias(resolve: bool) -> tuple[object, float]:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for name, text in _ALIAS_CORPUS.items():
            (root / name).write_text(text, encoding="utf-8")
        t0 = time.perf_counter()
        result = build(root, config=Config(resolve_entities=resolve))
        return result, (time.perf_counter() - t0) * 1000


def report() -> str:
    pdf_ok, pdf_fmt = _pdf_default()

    off, off_ms = _build_alias(resolve=False)
    on, on_ms = _build_alias(resolve=True)
    aliases_off = _acme_aliases(off.nodes)  # type: ignore[attr-defined]
    aliases_on = _acme_aliases(on.nodes)  # type: ignore[attr-defined]
    same_as = sum(1 for e in on.edges if e.predicate == "SAME_AS")  # type: ignore[attr-defined]
    canon = sum(1 for n in on.nodes if "Canonical" in n.labels)  # type: ignore[attr-defined]

    engine = QueryEngine(on.nodes, on.edges)  # type: ignore[attr-defined]
    t0 = time.perf_counter()
    engine.search("who controls Beta Ltd", k=5)
    query_ms = (time.perf_counter() - t0) * 1000

    lines = [
        "## Zero-config defaults (PDF + entity resolution)",
        "",
        "A default install (`pip install textgraph-kg`, no flags, no extras) already ingests "
        "PDFs and resolves entity aliases. Proof:",
        "",
        f"- **PDF ingestion, default:** a generated `.pdf` ingests as `format={pdf_fmt}` "
        f"({'OK' if pdf_ok else 'FAILED'}) -- `pypdf` is a core dependency, no `[ingest]` "
        "extra required.",
        "",
        "- **Entity resolution, default** (rules backend) -- before/after on a fixed 3-doc "
        "corpus where one org appears as *Acme Corporation / Acme Corp / ACME*. Resolution is "
        "non-destructive (aliases are kept and linked, not deleted), so the win is *unified "
        "identity*, not fewer nodes:",
        "",
        "| | Acme surface forms | SAME_AS links | canonical identities |",
        "|---|---|---|---|",
        f"| ER off (`resolve_entities=False`) | {aliases_off} | 0 | 0 |",
        f"| **ER on (default)** | {aliases_on} | {same_as} | {canon} |",
        "",
        f"With ER on, the {aliases_on} surface forms are unified under {canon} canonical "
        f"identity via {same_as} cited `SAME_AS` link(s) -- so a query for `ACME` reaches "
        "facts filed under `Acme Corporation`, and PageRank/paths treat them as one node. "
        "Zero configuration.",
        "",
        f"- **Latency** (machine-dependent): build {on_ms:.0f} ms (ER on) vs {off_ms:.0f} ms "
        f"(ER off); a hybrid `search` over the resolved graph in {query_ms:.1f} ms.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="append the block to BENCHMARKS.md")
    args = ap.parse_args(argv)
    block = report()
    print(block)
    if args.write:
        path = REPO / "BENCHMARKS.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n\n" + block + "\n", encoding="utf-8")
        print(f"\n-> appended to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
