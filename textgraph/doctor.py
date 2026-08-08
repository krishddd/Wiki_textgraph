"""``textgraph doctor`` — a read-only environment health check.

First-time users hit environment issues (a missing optional extra, an unwritable
artifact directory, a broken determinism guarantee on their machine) with no single
command to triage before filing a support issue. ``doctor`` is that command.

Design (following the converged ``<tool> doctor`` pattern — Codex, coder-doctor,
WP-CLI, etc.):

* **Read-only by default.** No prompts, repairs, migrations, or state writes. There is
  deliberately no ``--fix`` in v1.
* **Stable check names.** Every check has a kebab-case name so ``--check <name>`` can run
  one in isolation and docs/errors can reference it precisely.
* **Two formats, one result object.** :func:`run_checks` returns a list of :class:`Check`;
  the CLI renders it human-readable by default and as JSON under ``--json`` (a CI gate).

The marquee check is ``determinism``: it builds a tiny corpus twice, right now, on this
machine, and asserts the two ``graph.json`` byte blobs are identical — local confirmation
of the exact guarantee CI enforces.
"""

from __future__ import annotations

import importlib.util
import platform
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Check status values, in ascending severity.
OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True)
class Check:
    """The outcome of one named health check."""

    name: str
    status: str  # OK | WARN | FAIL
    detail: str

    @property
    def ok(self) -> bool:
        return self.status != FAIL

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _installed(module: str) -> bool:
    """True if ``module`` is importable, without importing it (no side effects)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # ValueError: e.g. a namespace-package edge case
        return False


def _check_python() -> Check:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 11):
        return Check("python-version", FAIL, f"Python {ver} < required 3.11")
    return Check("python-version", OK, f"Python {ver} on {platform.system()}")


def _check_core() -> Check:
    # The package and its config machinery must import and compute a config hash.
    try:
        from textgraph import __version__
        from textgraph.core.config import Config

        digest = Config().config_hash()
    except Exception as exc:  # pragma: no cover - a broken install is hard to simulate
        return Check("core-import", FAIL, f"textgraph failed to import: {exc}")
    return Check("core-import", OK, f"textgraph {__version__} (config_hash {digest[:12]})")


def _check_tempdir_writable() -> Check:
    # Proxy for artifact-directory and DuckDB-path writability: can we write at all?
    try:
        with tempfile.NamedTemporaryFile(prefix="textgraph-doctor-", suffix=".tmp") as fh:
            fh.write(b"ok")
            fh.flush()
        return Check("tempdir-writable", OK, f"temp dir writable ({tempfile.gettempdir()})")
    except OSError as exc:  # pragma: no cover - unwritable temp is environment-specific
        return Check("tempdir-writable", FAIL, f"cannot write to temp dir: {exc}")


def _check_ingest_pdf() -> Check:
    # pypdf moved to CORE deps in 3.0 (PDF text ingestion is default). Its absence is a
    # broken install, not a missing optional.
    if _installed("pypdf"):
        extras = "Docling available" if _installed("docling") else "Docling [ingest] absent"
        return Check("ingest-pdf", OK, f"pypdf present (PDF text ingestion on); {extras}")
    return Check("ingest-pdf", FAIL, "pypdf missing (a core dependency) - reinstall textgraph")


def _optional_check(name: str, modules: list[str], extra: str, what: str) -> Check:
    """Report an optional backend: OK if all its modules import, WARN otherwise (non-fatal)."""
    missing = [m for m in modules if not _installed(m)]
    if not missing:
        return Check(name, OK, f"{what} available")
    return Check(name, WARN, f"{what} disabled - install `{extra}` (missing: {', '.join(missing)})")


def _check_duckdb() -> Check:
    # DuckDB backs .duckdb snapshots and the [er]/[graph] backends.
    if _installed("duckdb"):
        return Check("duckdb", OK, "duckdb present (.duckdb snapshots + [er]/[graph] backends)")
    return Check("duckdb", WARN, "duckdb absent - .duckdb snapshots need `[graph]`")


def _check_determinism() -> Check:
    """Build a tiny corpus twice and assert byte-identical ``graph.json`` on THIS machine."""
    try:
        from textgraph.pipeline import build_graph_bytes

        with tempfile.TemporaryDirectory(prefix="textgraph-doctor-") as tmp:
            doc = Path(tmp) / "sample.md"
            doc.write_text(
                "# Acme Corp\n\nAlice is the CTO of Acme Corp. Acme Corp controls Beta Ltd.\n",
                encoding="utf-8",
            )
            first = build_graph_bytes(Path(tmp))
            second = build_graph_bytes(Path(tmp))
    except Exception as exc:  # pragma: no cover - a build crash surfaces as a FAIL detail
        return Check("determinism", FAIL, f"build failed: {exc}")
    if first != second:
        return Check("determinism", FAIL, "graph.json is NOT byte-identical across two builds")
    return Check("determinism", OK, f"byte-identical graph.json, 2 builds ({len(first)} bytes)")


# Registry: stable name -> zero-arg check. Order defines report order.
_CHECKS: dict[str, Callable[[], Check]] = {
    "python-version": _check_python,
    "core-import": _check_core,
    "tempdir-writable": _check_tempdir_writable,
    "ingest-pdf": _check_ingest_pdf,
    "extra-ingest": lambda: _optional_check(
        "extra-ingest", ["docling"], "[ingest]", "Docling layout/OCR ingestion"
    ),
    "extra-ie": lambda: _optional_check(
        "extra-ie", ["spacy", "gliner"], "[ie]", "GLiNER/spaCy IE backend"
    ),
    "extra-er": lambda: _optional_check(
        "extra-er", ["splink"], "[er]", "Splink probabilistic entity resolution"
    ),
    "extra-graph": lambda: _optional_check(
        "extra-graph", ["networkx", "leidenalg"], "[graph]", "Leiden communities + DuckDB store"
    ),
    "duckdb": _check_duckdb,
    "determinism": _check_determinism,
}


def check_names() -> list[str]:
    """Stable, ordered list of every check name (for ``--check`` validation and help)."""
    return list(_CHECKS)


def run_checks(names: list[str] | None = None) -> list[Check]:
    """Run all checks, or only the named subset, in registry order.

    Raises :class:`KeyError` if a requested name is unknown (the CLI turns that into a
    clean error listing the valid names).
    """
    if names is None:
        selected = list(_CHECKS)
    else:
        unknown = [n for n in names if n not in _CHECKS]
        if unknown:
            raise KeyError(unknown[0])
        selected = names
    return [_CHECKS[n]() for n in selected]


_ICON = {OK: "[ok]  ", WARN: "[warn]", FAIL: "[fail]"}


def format_text(checks: list[Check]) -> str:
    """Human-readable report (ASCII only, for cp1252 consoles)."""
    lines = ["textgraph doctor"]
    width = max((len(c.name) for c in checks), default=0)
    for c in checks:
        lines.append(f"  {_ICON[c.status]} {c.name.ljust(width)}  {c.detail}")
    fails = sum(1 for c in checks if c.status == FAIL)
    warns = sum(1 for c in checks if c.status == WARN)
    oks = sum(1 for c in checks if c.status == OK)
    lines.append("")
    if fails:
        lines.append(f"{fails} failed, {warns} warning(s), {oks} ok -> environment NOT healthy")
    elif warns:
        lines.append(f"{warns} optional backend(s) not installed, {oks} ok -> core is healthy")
    else:
        lines.append(f"all {oks} checks passed -> environment healthy")
    return "\n".join(lines)
