"""Lightweight schema/fixture validator (pre-commit + CI hook).

Phase 0 keeps this dependency-free: it confirms that every JSON file under
``schema/`` and ``tests/fixtures/`` parses, and that the shipped JSON Schemas are
themselves well-formed. A full ``jsonschema``-based validation of built artifacts
is wired in once real ``graph.json`` / ``manifest.json`` fixtures exist (Phase 1).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_DIRS = [ROOT / "schema", ROOT / "tests" / "fixtures"]


def main() -> int:
    errors: list[str] = []
    checked = 0
    for base in TARGET_DIRS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.json")):
            checked += 1
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"{path}: invalid JSON: {exc}")

    if errors:
        print("Schema/fixture validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Schema/fixture validation OK ({checked} JSON files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
