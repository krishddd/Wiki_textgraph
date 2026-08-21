"""Extraction schema (v5.5.0) — an opt-in ontology contract for the LLM relation pass.

Constrains the extractor's prompt to an allowed vocabulary AND validates its output (drops
off-ontology triples), so a schema raises precision. Pinned on Config -> folded into config_hash,
so changing the schema re-queries rather than reusing a cached response. The LLM pass stays
opt-in and GENERATED-quarantined; the deterministic core is untouched.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from textgraph.core.config import Config
from textgraph.core.extract_schema import ExtractionSchema
from textgraph.l4_llm_optional.cache import PromptCache
from textgraph.l4_llm_optional.extract import extract_llm_relations
from textgraph.l4_llm_optional.schema import (
    load_schema,
    schema_from_field_specs,
    schema_from_mapping,
    schema_from_pydantic,
)
from textgraph.store.base import SourceSpan


class _StubClient:
    model = "stub-model"

    def __init__(self, response: str) -> None:
        self._response = response
        self.systems: list[str] = []
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.systems.append(system)
        self.calls += 1
        return self._response


def _span() -> SourceSpan:
    return SourceSpan(doc_id="d1", start=0, end=10, hash="h")


# --- the schema type ---------------------------------------------------------


def test_normalized_uppercases_dedupes_and_folds_relations() -> None:
    s = ExtractionSchema(
        entity_types=("Org", "Org"),
        predicates=("regulates", "amends"),
        relations=(("Regulation", "applies to", "Product"),),
    ).normalized()
    assert s.predicates == ("AMENDS", "APPLIES_TO", "REGULATES")  # sorted, upper-snake, deduped
    # entity types absorb the relation's endpoints; sorted + deduped.
    assert s.entity_types == ("Org", "Product", "Regulation")
    assert s.relations == (("Regulation", "APPLIES_TO", "Product"),)


def test_prompt_hint_is_deterministic_and_lists_the_vocabulary() -> None:
    s = ExtractionSchema(predicates=("REGULATES", "AMENDS")).normalized()
    h = s.prompt_hint()
    assert h == s.prompt_hint()  # deterministic
    assert "AMENDS" in h and "REGULATES" in h and h.startswith(" ")
    assert ExtractionSchema().prompt_hint() == ""  # empty schema adds nothing


def test_validate_drops_off_ontology_predicates() -> None:
    s = ExtractionSchema(predicates=("REGULATES",)).normalized()
    triples = [("A", "REGULATES", "B"), ("A", "OWNS", "B")]
    assert s.validate(triples) == [("A", "REGULATES", "B")]
    assert s.allows("regulates") and not s.allows("owns")
    # An empty schema is a no-op (any predicate allowed).
    assert ExtractionSchema().validate(triples) == triples


# --- loaders -----------------------------------------------------------------


def test_load_schema_from_json(tmp_path: Path) -> None:
    p = tmp_path / "ontology.json"
    p.write_text(
        json.dumps(
            {
                "entity_types": ["Organization"],
                "predicates": ["regulates"],
                "relations": [["Regulation", "applies_to", "Product"]],
            }
        ),
        encoding="utf-8",
    )
    s = load_schema(p)
    assert "REGULATES" in s.predicates and "APPLIES_TO" in s.predicates
    assert ("Regulation", "APPLIES_TO", "Product") in s.relations


def test_schema_from_mapping_ignores_malformed_relations() -> None:
    s = schema_from_mapping({"relations": [["A", "B"], ["A", "rel", "C"]]})  # first is malformed
    assert s.relations == (("A", "REL", "C"),)


def test_schema_from_field_specs() -> None:
    s = schema_from_field_specs(["Org", "Person"], [("Org", "employs", "Person")])
    assert s.predicates == ("EMPLOYS",)
    assert ("Org", "EMPLOYS", "Person") in s.relations


def test_schema_from_pydantic_without_the_extra_raises_clearly() -> None:
    if importlib.util.find_spec("pydantic") is not None:
        return  # only meaningful when the [schema] extra is absent (the lean default)
    from textgraph.l0_ingest.base import UnsupportedFormat

    try:
        schema_from_pydantic()
        raised = False
    except UnsupportedFormat as exc:
        raised = "pydantic" in str(exc)
    assert raised


# --- config hashing (cache invalidation) -------------------------------------


def test_schema_changes_the_config_hash() -> None:
    base = Config(llm_extract=True)
    a = Config(llm_extract=True, extract_schema=ExtractionSchema(predicates=("REGULATES",)))
    b = Config(llm_extract=True, extract_schema=ExtractionSchema(predicates=("AMENDS",)))
    assert base.config_hash() != a.config_hash()  # adding a schema changes the hash
    assert a.config_hash() != b.config_hash()  # a different schema changes it again
    assert a.config_hash() == a.config_hash()  # deterministic


# --- extractor integration ---------------------------------------------------


def test_extractor_constrains_prompt_and_filters_output(tmp_path: Path) -> None:
    # The model returns one on-ontology and one off-ontology triple; only the allowed one lands.
    resp = json.dumps(
        [
            {"subject": "Commission", "predicate": "regulates", "object": "Body"},
            {"subject": "Commission", "predicate": "dislikes", "object": "Body"},
        ]
    )
    client = _StubClient(resp)
    schema = ExtractionSchema(predicates=("REGULATES",)).normalized()
    chunks = [("chunk:1", "The Commission regulates and dislikes the Body, per the file.", _span())]
    _nodes, edges = extract_llm_relations(chunks, client, PromptCache(tmp_path), schema=schema)
    preds = {e.predicate for e in edges}
    assert preds == {"REGULATES"}  # the off-ontology DISLIKES was dropped
    assert "REGULATES" in client.systems[0]  # the allow-list was put in the system prompt


def test_schema_change_invalidates_the_prompt_cache(tmp_path: Path) -> None:
    # Same chunk + model, different schema -> a fresh call (the hint is folded into the cache key).
    resp = json.dumps([{"subject": "A", "predicate": "regulates", "object": "B"}])
    chunks = [("chunk:1", "A regulates B in the matter described within this document.", _span())]
    cache = PromptCache(tmp_path)
    c1 = _StubClient(resp)
    extract_llm_relations(chunks, c1, cache, schema=ExtractionSchema(predicates=("REGULATES",)))
    c2 = _StubClient(resp)
    extract_llm_relations(chunks, c2, cache, schema=ExtractionSchema(predicates=("AMENDS",)))
    assert c1.calls == 1 and c2.calls == 1  # the second schema did not reuse the first's cache
