"""Collaborative mode — attribution, assignments, version sync, multi-process merge."""

import json
from pathlib import Path

from textgraph.console.annotations import AnnotationStore


def test_attribution_is_recorded_and_versioned(tmp_path: Path) -> None:
    s = AnnotationStore(tmp_path / "c.json")
    assert s.version == 0
    stored = s.set(
        "e:acme", status="confirmed", note="ok", author="Dana", at="2026-01-01T00:00:00Z"
    )
    assert s.version == 1
    assert stored["author"] == "Dana" and stored["status"] == "confirmed"
    payload = s.payload(analyst="Dana")
    assert payload["annotations"]["e:acme"]["updated"] == "2026-01-01T00:00:00Z"
    assert payload["analyst"] == "Dana"
    assert payload["activity"] and payload["activity"][-1]["author"] == "Dana"


def test_assignments_round_trip_and_unassign(tmp_path: Path) -> None:
    s = AnnotationStore(tmp_path / "c.json")
    assert s.assign("e:acme", "Reed", author="Dana", at="t") == "Reed"
    assert s.payload()["assignments"]["e:acme"] == "Reed"
    # Empty analyst clears the assignment.
    assert s.assign("e:acme", "", author="Dana", at="t") is None
    assert "e:acme" not in s.payload()["assignments"]


def test_version_is_monotonic_across_writes(tmp_path: Path) -> None:
    s = AnnotationStore(tmp_path / "c.json")
    versions = []
    for i in range(3):
        s.set(f"e:{i}", status="pending", note="", author="A", at="t")
        versions.append(s.version)
    s.assign("e:0", "B", author="A", at="t")
    versions.append(s.version)
    assert versions == sorted(set(versions)) == [1, 2, 3, 4]


def test_reload_before_write_merges_a_second_console(tmp_path: Path) -> None:
    # Two stores on one sidecar file (two console processes). A write from one must not clobber
    # the other's untouched nodes — the second console reloads before writing.
    path = tmp_path / "shared.json"
    a = AnnotationStore(path)
    b = AnnotationStore(path)
    a.set("e:one", status="confirmed", note="by A", author="A", at="t")
    b.set("e:two", status="disputed", note="by B", author="B", at="t")  # b reloads, sees e:one
    final = AnnotationStore(path).payload()
    assert set(final["annotations"]) == {"e:one", "e:two"}  # neither write lost the other


def test_payload_reloads_so_a_second_console_sees_the_first(tmp_path: Path) -> None:
    # The cross-process sync that makes collaboration work: console B's read must reflect
    # console A's write. Without reload-before-read, B would serve its stale in-memory version 0.
    path = tmp_path / "shared.json"
    dana = AnnotationStore(path)
    reed = AnnotationStore(path)  # a second console process, started fresh
    dana.set("e:acme", status="confirmed", note="by Dana", author="Dana", at="t")
    dana.assign("e:acme", "Reed", author="Dana", at="t")
    seen = reed.payload(analyst="Reed")  # Reed polls -> must see Dana's edits
    assert seen["version"] == 2
    assert seen["annotations"]["e:acme"]["author"] == "Dana"
    assert seen["assignments"]["e:acme"] == "Reed"


def test_backward_compatible_with_v411_flat_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"e:x": {"status": "disputed", "note": "old"}}), encoding="utf-8")
    s = AnnotationStore(path)
    assert s.all()["e:x"]["status"] == "disputed"
    # First write upgrades it to the new nested format.
    s.set("e:y", status="pending", note="", author="A", at="t")
    doc = json.loads(path.read_text())
    assert "annotations" in doc and "version" in doc


def test_corrupt_sidecar_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    s = AnnotationStore(path)  # must not raise
    assert s.all() == {} and s.version == 0


def test_collab_payload_carries_identity_annotations_and_assignments() -> None:
    # The shape the /api/collab endpoint returns to the console.
    s = AnnotationStore(None)
    s.set("e:a", status="confirmed", note="x", author="Dana", at="t")
    s.assign("e:a", "Reed", author="Dana", at="t")
    payload = s.payload(analyst="Dana")
    assert payload["version"] == 2
    assert payload["annotations"]["e:a"]["author"] == "Dana"
    assert payload["assignments"]["e:a"] == "Reed"
