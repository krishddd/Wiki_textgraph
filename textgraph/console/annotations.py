"""Analyst annotation sidecar — human judgments kept *beside* the deterministic graph.

An investigator needs to record what they think — "this entity is confirmed", "that relation is
disputed", a free-text note — without corrupting the reproducible artifact. So annotations live
in a separate ``annotations.json`` sidecar, keyed by node id; ``graph.json`` is never touched and
stays byte-identical (G1). This is also the seed of collaborative review: the graph is the shared
immutable ground truth, the sidecar is the mutable overlay.

Pure and dependency-free. The store is a thin dict wrapper with atomic-ish disk persistence when
a path is configured; when it isn't, annotations are in-memory for the session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# The judgments an analyst can attach. "none" clears the status but may keep a note.
_STATUSES = frozenset({"none", "confirmed", "disputed", "pending"})


def _clean(status: str, note: str) -> dict[str, str]:
    st = status if status in _STATUSES else "none"
    return {"status": st, "note": note.strip()[:2000]}


class AnnotationStore:
    """Node-id -> {status, note}, optionally persisted to a JSON sidecar."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._data: dict[str, dict[str, str]] = {}
        if self.path and self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for nid, ann in raw.items():
                        if isinstance(ann, dict):
                            self._data[str(nid)] = _clean(
                                str(ann.get("status", "none")), str(ann.get("note", ""))
                            )
            except (ValueError, OSError):
                self._data = {}  # a corrupt sidecar starts empty rather than crashing

    def all(self) -> dict[str, dict[str, str]]:
        """Every annotation (only non-empty ones are stored)."""
        return dict(self._data)

    def set(self, node_id: str, *, status: str = "none", note: str = "") -> dict[str, str]:
        """Set (or clear) one node's annotation and persist. Returns the stored value."""
        cleaned = _clean(status, note)
        if cleaned["status"] == "none" and not cleaned["note"]:
            self._data.pop(node_id, None)  # empty annotation = remove
        else:
            self._data[node_id] = cleaned
        self._persist()
        return cleaned

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        tmp.replace(self.path)  # atomic-ish swap so a reader never sees a half-written file

    def to_payload(self) -> dict[str, Any]:
        return {"annotations": self._data, "persisted": self.path is not None}
