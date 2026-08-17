"""Opt-in change alerts for ``textgraph watch`` — post a graph diff to a webhook.

The only feature in TextGraph that reaches the network on the write path, and it is off unless
``--webhook`` is given. On each rebuild after the first, the watcher diffs the previous and
current graphs and, if anything changed (optionally only for a watchlist of entities), POSTs a
compact JSON summary to the URL. The payload is Slack/Teams-compatible (a ``text`` headline plus
the structured diff), so a channel gets notified when a new contradiction appears, a key entity
is added, or a relation's confidence moves — without anyone watching the console.

Deterministic and dependency-free (stdlib ``urllib``). A failed POST is logged, never fatal:
the watcher keeps running.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from textgraph.l9_artifacts.diff import GraphDiff


def build_payload(diff: GraphDiff, *, source: str | None = None) -> dict[str, object]:
    """Assemble the webhook JSON body from a diff (Slack-compatible ``text`` + structured data)."""
    headline = f"TextGraph: {diff.summary()}"
    if source:
        headline += f" ({source})"
    return {"text": headline, "summary": diff.summary(), "diff": diff.to_dict()}


def post_webhook(
    url: str,
    payload: dict[str, object],
    *,
    timeout: float = 10.0,
    opener: Callable[[urllib.request.Request, float], object] | None = None,
) -> bool:
    """POST ``payload`` as JSON to ``url``. Returns True on 2xx, False on any failure.

    ``opener`` is injectable so tests never touch the network. Never raises — a webhook is a
    best-effort side channel; the watcher must survive a flaky endpoint.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    send = opener if opener is not None else _default_open
    try:
        resp = send(req, timeout)
        status = int(getattr(resp, "status", 0) or getattr(resp, "code", 0) or 0)
        return 200 <= status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _default_open(req: urllib.request.Request, timeout: float) -> object:
    return urllib.request.urlopen(req, timeout=timeout)
