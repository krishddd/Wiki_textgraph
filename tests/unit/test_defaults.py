"""Investigator zero-config defaults — regression guard.

The moat is that the *default* install (no flags, no extras) already does the investigator
happy path: ingest PDFs and resolve entity aliases. These tests lock that in so it can never
silently regress behind an extra or a config flag again.
"""

import tempfile
from pathlib import Path

from textgraph.core.config import Config
from textgraph.l0_ingest import ingest_path
from textgraph.pipeline import build


def test_pdf_ingests_on_the_default_install() -> None:
    # pypdf is a CORE dependency (not the [ingest] extra), so a .pdf reads out of the box.
    from pypdf import PdfWriter

    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "note.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(pdf, "wb") as fh:
            writer.write(fh)
        ir = ingest_path(pdf)
    assert ir.format == "pdf"
    assert ir.doc_id  # content-addressed id assigned


def test_entity_resolution_is_on_by_default() -> None:
    cfg = Config()
    assert cfg.resolve_entities is True
    assert cfg.er_backend == "rules"  # deterministic, dependency-free default (not Splink)


def test_default_build_resolves_aliases_without_flags() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a.md").write_text("Acme Corporation controls Beta Ltd.", encoding="utf-8")
        (root / "b.md").write_text("Acme Corp transferred funds to Beta Ltd.", encoding="utf-8")
        (root / "c.md").write_text("ACME is the beneficial owner of Beta Ltd.", encoding="utf-8")
        r = build(root)  # DEFAULT config — no --er, no extras
    same_as = [e for e in r.edges if e.predicate == "SAME_AS"]
    canonical = [n for n in r.nodes if "Canonical" in n.labels]
    assert same_as, "default build must resolve the Acme aliases (SAME_AS)"
    assert canonical, "default build must produce a canonical identity"
    assert r.er_stats.get("same_as_edges", 0) == len(same_as)


def test_pdf_is_a_core_dependency_not_an_extra() -> None:
    # Guard the packaging: pypdf must stay in [project.dependencies], never behind [ingest].
    import tomllib

    root = Path(__file__).resolve().parent.parent.parent
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    core = " ".join(pyproject["project"]["dependencies"])
    assert "pypdf" in core, "pypdf must be a core dependency (PDF ingestion is default)"
