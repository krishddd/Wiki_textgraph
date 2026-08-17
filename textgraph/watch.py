"""``textgraph watch`` — rebuild artifacts when the corpus changes (G5).

Polls a corpus directory; whenever a file's *content* changes (detected by blake3, so
a mere touch doesn't trigger work), it runs an **incremental** rebuild — only edited
files are re-extracted, thanks to the per-document IE cache — and re-writes the L9
artifacts. Change detection is content-addressed, not mtime-based, so it is robust and
deterministic. Watching keeps the on-disk graph continuously in sync with a live
case folder.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.content_address import blake3_hex
from textgraph.l9_artifacts import write_artifacts
from textgraph.pipeline import BuildResult, _iter_corpus_files, build


def corpus_signature(root: str | Path) -> str:
    """Content-addressed signature of a corpus: changes iff a file's bytes change."""
    parts = [f"{p.as_posix()}:{blake3_hex(p.read_bytes())}" for p in _iter_corpus_files(Path(root))]
    return blake3_hex("\n".join(parts).encode("utf-8"))


def watch(
    root: str | Path,
    out_dir: str | Path,
    *,
    cache_dir: str | Path | None = None,
    config: Config | None = None,
    interval: float = 2.0,
    iterations: int = 0,
    on_build: Callable[[BuildResult], None] | None = None,
    on_diff: Callable[[BuildResult, BuildResult], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Watch ``root``; rebuild into ``out_dir`` on each content change.

    ``iterations`` bounds the number of poll cycles (0 = run forever); tests pass a
    finite count. Returns the last-seen corpus signature. ``sleep`` is injectable so
    tests need not actually wait.

    ``on_diff(prev, curr)`` fires on every rebuild *after the first*, with the previous and
    current builds, so a caller can diff them (for alerts/watchlists) without re-plumbing.
    """
    out_dir = Path(out_dir)
    cache_dir = Path(cache_dir) if cache_dir is not None else out_dir / ".cache"
    # Guard the footgun: if artifacts landed inside the watched dir they'd be
    # re-ingested (graph.json / .md / .html are all ingestable) and loop forever.
    root_res = Path(root).resolve()
    for sub in (out_dir, cache_dir):
        if sub.resolve() == root_res or sub.resolve().is_relative_to(root_res):
            raise ValueError(
                f"output/cache dir {sub} must be outside the watched corpus {root} "
                "(else its own artifacts get re-ingested)"
            )
    prev_sig: str | None = None
    prev_result: BuildResult | None = None
    count = 0
    while iterations == 0 or count < iterations:
        sig = corpus_signature(root)
        if sig != prev_sig:
            result = build(root, config=config, cache_dir=cache_dir)
            write_artifacts(
                out_dir,
                config_hash=result.config_hash,
                results=result.results,
                nodes=result.nodes,
                edges=result.edges,
                timings_ms=result.timings_ms,
                ie_stats=result.ie_stats,
                er_stats=result.er_stats,
                graph_stats=result.graph_stats,
            )
            prev_sig = sig
            if on_build is not None:
                on_build(result)
            if on_diff is not None and prev_result is not None:
                on_diff(prev_result, result)
            prev_result = result
        count += 1
        if iterations == 0 or count < iterations:
            sleep(interval)
    return prev_sig
