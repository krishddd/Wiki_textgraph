"""Extraction schema (contract) for the optional LLM relation pass (L4).

A user can pin an **ontology** for the opt-in LLM extractor: the set of entity types and
predicates it is allowed to emit (optionally with typed relation signatures). The schema does
two things, both deterministic and dependency-free:

* **Constrains the prompt** — the allowed predicates/types/shapes are appended to the system
  prompt, so the model is told exactly what vocabulary to use (schema-guided extraction).
* **Validates the output** — any emitted triple whose predicate is outside the allow-list is
  dropped, so a schema raises precision instead of trusting the model to obey the instructions.

It lives in ``core`` (not ``l4``) because it is pinned on :class:`~textgraph.core.config.Config`
and therefore folded into ``config_hash`` (G1): change the schema and the LLM prompt cache
invalidates, so a re-run re-extracts under the new contract. The LLM pass stays opt-in and its
output stays ``GENERATED``-quarantined — the schema tightens that pass, it never touches the
deterministic core.

Load one from JSON with :func:`textgraph.l4_llm_optional.schema.load_schema`, or derive one from
Pydantic models with :func:`~textgraph.l4_llm_optional.schema.schema_from_pydantic`.
"""

from __future__ import annotations

from dataclasses import dataclass


def _canon_pred(pred: str) -> str:
    """Canonical predicate token: UPPER_SNAKE_CASE (matches the extractor's normalization)."""
    return pred.strip().upper().replace(" ", "_")


@dataclass(frozen=True)
class ExtractionSchema:
    """An allow-list contract for LLM relation extraction (all fields optional).

    * ``entity_types`` — permitted entity type labels (prompt guidance).
    * ``predicates`` — permitted predicate names; **enforced** on the output.
    * ``relations`` — permitted ``(subject_type, PREDICATE, object_type)`` signatures (prompt
      guidance; output is filtered at the predicate level, since triples carry names not types).
    """

    entity_types: tuple[str, ...] = ()
    predicates: tuple[str, ...] = ()
    relations: tuple[tuple[str, str, str], ...] = ()

    def normalized(self) -> ExtractionSchema:
        """A deterministic, de-duplicated, sorted form (so ``config_hash`` is order-stable)."""
        ents = tuple(sorted({e.strip() for e in self.entity_types if e.strip()}))
        preds = tuple(sorted({_canon_pred(p) for p in self.predicates if p.strip()}))
        # A relation's predicate joins the predicate allow-list, so an ontology given only as
        # signatures still constrains + validates.
        rel_set = {
            (s.strip(), _canon_pred(p), o.strip())
            for s, p, o in self.relations
            if s.strip() and p.strip() and o.strip()
        }
        rels = tuple(sorted(rel_set))
        preds = tuple(sorted(set(preds) | {p for _s, p, _o in rels}))
        ents = tuple(sorted(set(ents) | {s for s, _p, _o in rels} | {o for _s, _p, o in rels}))
        return ExtractionSchema(ents, preds, rels)

    def is_empty(self) -> bool:
        return not (self.entity_types or self.predicates or self.relations)

    def prompt_hint(self) -> str:
        """The constraint text appended to the extractor's system prompt (deterministic)."""
        parts: list[str] = []
        if self.predicates:
            parts.append(
                "Only use these predicates, exactly as written (UPPER_SNAKE_CASE): "
                + ", ".join(self.predicates)
                + ". Discard any relationship that does not fit one of them."
            )
        if self.entity_types:
            parts.append(
                "Entities should be one of these types: " + ", ".join(self.entity_types) + "."
            )
        if self.relations:
            sigs = "; ".join(f"{s} -{p}-> {o}" for s, p, o in self.relations)
            parts.append("Prefer these relation shapes: " + sigs + ".")
        return (" " + " ".join(parts)) if parts else ""

    def allows(self, predicate: str) -> bool:
        """Whether ``predicate`` is permitted (any predicate is allowed if none are listed)."""
        return not self.predicates or _canon_pred(predicate) in set(self.predicates)

    def validate(self, triples: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
        """Drop triples whose predicate is outside the allow-list (no-op if none is set)."""
        if not self.predicates:
            return list(triples)
        return [t for t in triples if self.allows(t[1])]
