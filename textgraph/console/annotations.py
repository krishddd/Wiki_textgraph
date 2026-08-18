"""Collaboration sidecar — human judgments + teamwork kept *beside* the deterministic graph.

Analysts need to record what they think ("confirmed" / "disputed" / "pending" + a note), divide a
case (assign entities to each other), and see each other's work as it happens — without touching
the reproducible artifact. So all of that lives in a separate sidecar JSON, keyed by node id;
``graph.json`` is never written and stays byte-identical (G1). The split is the whole design: the
graph is the immutable shared ground truth, the sidecar is the mutable overlay.

The overlay carries **attribution** (author + updated time), **assignments** (who owns an entity),
a monotonic **version** for cheap live-sync polling, and a bounded **activity log**. Identity is
*declared* (``console --analyst NAME``), not authenticated — it is collaboration convenience, not a
security boundary (that is ``--token`` / the access policy). It is explicitly non-deterministic
(timestamps, authors) precisely because it is not part of the reproducible build.

Multi-process safe: writes reload-before-write under a lock, so two consoles on one sidecar file
merge rather than clobber (per-node last-write-wins). Pure and dependency-free; a v4.11 flat
``annotations.json`` loads unchanged.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_STATUSES = frozenset({"none", "confirmed", "disputed", "pending"})
_MAX_ACTIVITY = 200


def _clean(status: str, note: str) -> tuple[str, str]:
    st = status if status in _STATUSES else "none"
    return st, note.strip()[:2000]


class AnnotationStore:
    """The collaboration overlay: annotations + assignments + version + activity, on a sidecar."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {}
        self._assignments: dict[str, str] = {}
        self._activity: list[dict[str, Any]] = []
        self._version = 0
        self._load()

    # -- persistence ----------------------------------------------------------------------

    def _load(self) -> None:
        if not (self.path and self.path.is_file()):
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return  # a corrupt sidecar starts empty rather than crashing
        if not isinstance(raw, dict):
            return
        # New format has an "annotations" key; a v4.11 flat file is {node: {status, note}}.
        anns = raw.get("annotations") if "annotations" in raw else raw
        self._data = {}
        if isinstance(anns, dict):
            for nid, ann in anns.items():
                if isinstance(ann, dict):
                    st, note = _clean(str(ann.get("status", "none")), str(ann.get("note", "")))
                    if st != "none" or note:
                        entry = {"status": st, "note": note}
                        if ann.get("author"):
                            entry["author"] = str(ann["author"])
                        if ann.get("updated"):
                            entry["updated"] = str(ann["updated"])
                        self._data[str(nid)] = entry
        assigns = raw.get("assignments", {})
        if isinstance(assigns, dict):
            self._assignments = {str(k): str(v) for k, v in assigns.items() if v}
        acts = raw.get("activity", [])
        if isinstance(acts, list):
            self._activity = [a for a in acts if isinstance(a, dict)][-_MAX_ACTIVITY:]
        self._version = int(raw.get("version", 0)) if str(raw.get("version", 0)).isdigit() else 0

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._snapshot(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)  # atomic-ish swap so a reader never sees a half-written file

    def _snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "annotations": self._data,
            "assignments": self._assignments,
            "activity": self._activity,
        }

    def _log(self, node_id: str, action: str, author: str, at: str) -> None:
        self._activity.append({"node": node_id, "action": action, "author": author, "at": at})
        if len(self._activity) > _MAX_ACTIVITY:
            del self._activity[: len(self._activity) - _MAX_ACTIVITY]

    # -- reads ----------------------------------------------------------------------------

    def all(self) -> dict[str, dict[str, str]]:
        return dict(self._data)

    @property
    def version(self) -> int:
        return self._version

    def payload(self, *, analyst: str | None = None) -> dict[str, Any]:
        """The full overlay for the console: annotations, assignments, version, recent activity.

        Reloads from disk first (under the lock) so a *second* console polling this endpoint sees
        the *first* console's writes — the cross-process sync that makes collaboration work. A
        no-op when there is no sidecar file (single-process, in-memory).
        """
        with self._lock:
            self._load()
            return {
                "version": self._version,
                "annotations": self._data,
                "assignments": self._assignments,
                "activity": self._activity[-50:],
                "analyst": analyst,
                "persisted": self.path is not None,
            }

    # Back-compat alias used by the read endpoint before collab mode.
    def to_payload(self) -> dict[str, Any]:
        return {"annotations": self._data, "persisted": self.path is not None}

    # -- writes (reload-before-write under a lock) ----------------------------------------

    def set(
        self, node_id: str, *, status: str = "none", note: str = "", author: str = "", at: str = ""
    ) -> dict[str, str]:
        """Set (or clear) one node's annotation, with attribution. Returns the stored value."""
        st, cleaned_note = _clean(status, note)
        with self._lock:
            self._load()  # merge any concurrent writes from another process first
            if st == "none" and not cleaned_note:
                self._data.pop(node_id, None)
                action = "cleared"
            else:
                entry = {"status": st, "note": cleaned_note}
                if author:
                    entry["author"] = author
                if at:
                    entry["updated"] = at
                self._data[node_id] = entry
                action = f"marked {st}" if st != "none" else "noted"
            self._version += 1
            if author:
                self._log(node_id, action, author, at)
            self._persist()
            return self._data.get(node_id, {"status": "none", "note": ""})

    def assign(self, node_id: str, analyst: str, *, author: str = "", at: str = "") -> str | None:
        """Assign an entity to ``analyst`` (empty string unassigns). Returns the new assignee."""
        with self._lock:
            self._load()
            analyst = analyst.strip()[:120]
            if analyst:
                self._assignments[node_id] = analyst
                action = f"assigned to {analyst}"
            else:
                self._assignments.pop(node_id, None)
                action = "unassigned"
            self._version += 1
            if author:
                self._log(node_id, action, author, at)
            self._persist()
            return self._assignments.get(node_id)
