"""Ways to build an :class:`ExtractionSchema` for the opt-in LLM extractor.

The schema type itself lives in :mod:`textgraph.core.extract_schema` (it is pinned on Config).
This module adds the on-ramps:

* :func:`load_schema` — from a small JSON file (the CLI / dependency-free path).
* :func:`schema_from_field_specs` — the pure derivation used by the Pydantic adapter (tested
  without Pydantic installed).
* :func:`schema_from_pydantic` — derive a schema from Pydantic v2 models (import-guarded; the
  Pydantic dep is optional and only this thin introspection shim needs it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textgraph.core.extract_schema import ExtractionSchema


def load_schema(path: str | Path) -> ExtractionSchema:
    """Load an :class:`ExtractionSchema` from a JSON file, normalized.

    Shape (all keys optional)::

        {"entity_types": ["Organization", "Regulation"],
         "predicates": ["REGULATES", "AMENDS"],
         "relations": [["Regulation", "APPLIES_TO", "Product"]]}
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return schema_from_mapping(data)


def schema_from_mapping(data: dict[str, Any]) -> ExtractionSchema:
    """Build a normalized schema from a plain mapping (the parsed JSON form)."""
    ents = tuple(str(e) for e in data.get("entity_types", []))
    preds = tuple(str(p) for p in data.get("predicates", []))
    rels = tuple(
        (str(r[0]), str(r[1]), str(r[2]))
        for r in data.get("relations", [])
        if isinstance(r, (list, tuple)) and len(r) == 3
    )
    return ExtractionSchema(ents, preds, rels).normalized()


def schema_from_field_specs(
    type_names: list[str],
    relation_fields: list[tuple[str, str, str]],
) -> ExtractionSchema:
    """Pure derivation shared by the Pydantic adapter (tested without the Pydantic dep).

    ``relation_fields`` is a list of ``(subject_type, field_name, object_type)``; each becomes a
    predicate ``FIELD_NAME`` (upper-snake) and a relation signature.
    """
    relations = tuple((s, field, o) for s, field, o in relation_fields)
    return ExtractionSchema(entity_types=tuple(type_names), relations=relations).normalized()


def schema_from_pydantic(*models: Any) -> ExtractionSchema:
    """Derive an :class:`ExtractionSchema` from Pydantic v2 models (import-guarded).

    Each model class is an entity type. A field whose (possibly ``list[...]``) annotation is
    another supplied model becomes a relation ``<ThisModel> -FIELD_NAME-> <ThatModel>``, so a set
    of linked Pydantic records defines the allowed entity types and predicates. Requires
    ``pydantic`` (the ``[schema]`` extra); raises :class:`UnsupportedFormat` if it is absent.
    """
    import importlib.util

    if importlib.util.find_spec("pydantic") is None:
        from textgraph.l0_ingest.base import UnsupportedFormat

        raise UnsupportedFormat(
            "schema_from_pydantic requires pydantic (the [schema] extra); "
            "pass a JSON schema via load_schema instead"
        )
    return _derive_from_models(models)


def _derive_from_models(models: tuple[Any, ...]) -> ExtractionSchema:  # pragma: no cover - [schema]
    """Introspect Pydantic models into (type_names, relation_fields). Needs pydantic installed."""
    model_names = {m.__name__ for m in models}
    type_names = [m.__name__ for m in models]
    relation_fields: list[tuple[str, str, str]] = []
    for model in models:
        for field_name, info in model.model_fields.items():
            target = _referenced_model(info.annotation, model_names)
            if target is not None:
                relation_fields.append((model.__name__, field_name, target))
    return schema_from_field_specs(type_names, relation_fields)


def _referenced_model(annotation: Any, model_names: set[str]) -> str | None:  # pragma: no cover
    """Return the model name an annotation references (through list[...]/Optional), if any."""
    import typing

    name = getattr(annotation, "__name__", None)
    if name in model_names:
        return str(name)
    for arg in typing.get_args(annotation):
        found = _referenced_model(arg, model_names)
        if found is not None:
            return found
    return None
