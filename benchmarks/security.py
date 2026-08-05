"""FGAC benchmark — the *cost* of security-aware traversal, and proof it blocks bleed.

Phase 9 DoD: "overhead measured; a red-team suite proves zero context-bleed." This harness
reports both numbers on the in-repo fixture, with zero downloads (G2):

* **Overhead** — the same queries run three ways: (a) no policy attached (the default
  install fast path), (b) a policy attached but *full-access* (grant everything), and
  (c) the same full-access policy security-aware. (b) isolates the guard's per-query cost
  from the walk; (b) and (a) must return byte-identical hits (the guard is transparent
  when nothing is restricted). p50/p95 latency is reported for each.
* **No-bleed** — a *restricted* policy (one document authorized) is run over queries that
  target the other document; the number of unauthorized hits that leak must be 0.

Usage:
    python -m benchmarks.security          # print the report
    python -m benchmarks.security --write   # also append the block to BENCHMARKS.md
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from textgraph.l8_retrieval import QueryEngine
from textgraph.pipeline import build
from textgraph.security import RebacStore, RelationTuple, SecurityContext, SecurityPolicy

REPO = Path(__file__).resolve().parent.parent
SECURE = REPO / "tests" / "fixtures" / "corpora" / "secure"
QUERIES = [
    "acme controls gamma holdings",
    "beneficial owner of delta trust",
    "shadow phantom transferred funds",
    "who wired money",
    "phantom bank controlled by",
]
SECRET = {"shadow llc", "phantom bank"}


def _p50_p95(samples: list[float]) -> tuple[float, float]:
    ordered = sorted(samples)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]
    return p50, p95


def _time_runs(fn: object, reps: int = 40) -> tuple[float, float]:
    latencies: list[float] = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()  # type: ignore[operator]
        latencies.append((time.perf_counter() - t0) * 1000)
    return _p50_p95(latencies)


def run() -> str:
    r = build(SECURE)
    plain = QueryEngine(r.nodes, r.edges)
    all_docs = sorted(plain._all_docs)
    public_doc = sorted(plain._node_docs[plain.resolve("Gamma Holdings")])[0]  # type: ignore[index]

    # (b/c) full-access policy: root may view every document.
    full = SecurityPolicy(
        rebac=RebacStore(RelationTuple(f"doc:{d}", "viewer", "user:root") for d in all_docs)
    )
    secured = QueryEngine(r.nodes, r.edges, policy=full)
    root = SecurityContext("root")

    # (d) restricted policy: alice may view the public document only.
    restricted = SecurityPolicy(
        rebac=RebacStore([RelationTuple(f"doc:{public_doc}", "viewer", "user:alice")])
    )
    guarded = QueryEngine(r.nodes, r.edges, policy=restricted)
    alice = SecurityContext("alice")

    # Transparency check: full-access secured hits == unsecured hits.
    identical = all(
        plain.search(q, k=10).to_dict() == secured.search(q, k=10, context=root).to_dict()
        for q in QUERIES
    )

    # No-bleed check: count unauthorized hits that leak under the restricted policy.
    leaked = 0
    for q in QUERIES:
        for h in guarded.search(q, k=10, context=alice).hits:
            if h.name.lower() in SECRET:
                leaked += 1

    base_p50, base_p95 = _time_runs(lambda: [plain.search(q, k=10) for q in QUERIES])
    sec_p50, sec_p95 = _time_runs(lambda: [secured.search(q, k=10, context=root) for q in QUERIES])
    overhead = (sec_p50 / base_p50 - 1.0) * 100 if base_p50 else 0.0

    lines = [
        "## Enterprise FGAC (Phase 9) - security-aware retrieval",
        "",
        f"Fixture: `tests/fixtures/corpora/secure` ({len(all_docs)} docs), {len(QUERIES)} queries, "
        "batch of all queries timed per rep.",
        "",
        "| Configuration | p50 (ms) | p95 (ms) |",
        "|---|---|---|",
        f"| baseline (no policy) | {base_p50:.2f} | {base_p95:.2f} |",
        f"| security-aware (full access) | {sec_p50:.2f} | {sec_p95:.2f} |",
        "",
        f"- Security-aware traversal overhead (full access): **{overhead:+.1f}%** p50.",
        f"- Transparency: full-access secured hits identical to unsecured: **{identical}**.",
        f"- No-bleed: unauthorized hits leaked under the restricted policy: **{leaked}** "
        "(red-team suite: `tests/integration/test_security_redteam.py`).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FGAC overhead + no-bleed benchmark")
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
