from textgraph.l3_encoder_ie import run_ie
from textgraph.l3_encoder_ie.canonicalize import canonical_predicate, entity_id
from textgraph.l3_encoder_ie.rules import extract_entities

WIRE = (
    "Acme Corp wired $2,000,000 to Beta Ltd on 2026-07-30. "
    "John Doe is the nominee director of Beta Ltd. "
    "Acme Corp controls Gamma Holdings. "
    "The company then transferred funds to Delta Trust. "
    "Beta Ltd did not transfer any funds to Omega Bank. "
    "Acme Corp may be linked to Sigma Partners."
)


def _types(ie):
    return {(e.etype, e.name) for e in ie.entities.values()}


def _rels(ie):
    return {(r.subject_id, r.predicate, r.object_id) for r in ie.relations}


def test_entity_types_detected() -> None:
    ents = {(m.etype, m.text) for m in extract_entities(WIRE)}
    assert ("Organization", "Acme Corp") in ents
    assert ("Organization", "Beta Ltd") in ents
    assert ("Person", "John Doe") in ents
    assert ("Money", "$2,000,000") in ents
    assert ("Date", "2026-07-30") in ents


def test_no_false_person_from_heading_words() -> None:
    ents = {m.text for m in extract_entities("Wire Transfer Analysis\n\nAcme Corp acted.")}
    assert "Wire Transfer" not in ents


def test_org_does_not_span_paragraph_break() -> None:
    ents = {m.text for m in extract_entities("Alpha Analysis\n\nBeta Ltd")}
    assert "Beta Ltd" in ents
    assert not any("Analysis" in e for e in ents)


def test_transferred_relation_with_amount() -> None:
    ie = run_ie(WIRE)
    acme = entity_id("Organization", "Acme Corp")
    beta = entity_id("Organization", "Beta Ltd")
    assert (acme, "TRANSFERRED", beta) in _rels(ie)
    transfer = next(
        r for r in ie.relations if r.subject_id == acme and r.predicate == "TRANSFERRED"
    )
    assert "$2,000,000" in transfer.amount


def test_control_and_director_relations() -> None:
    ie = run_ie(WIRE)
    rels = _rels(ie)
    assert (
        entity_id("Organization", "Acme Corp"),
        "CONTROLS",
        entity_id("Organization", "Gamma Holdings"),
    ) in rels
    assert (
        entity_id("Person", "John Doe"),
        "DIRECTOR_OF",
        entity_id("Organization", "Beta Ltd"),
    ) in rels


def test_coref_produces_inferred_relation() -> None:
    ie = run_ie(WIRE)
    # "The company then transferred funds to Delta Trust" -> subject via coref.
    inferred = [r for r in ie.relations if r.inferred]
    assert any(r.object_id == entity_id("Organization", "Delta Trust") for r in inferred)
    assert ie.pronouns_resolved > 0


def test_negation_polarity_preserved() -> None:
    ie = run_ie(WIRE)
    omega = entity_id("Organization", "Omega Bank")
    neg = [r for r in ie.relations if r.object_id == omega]
    assert neg and neg[0].polarity == "neg"


def test_hedged_modality_preserved() -> None:
    ie = run_ie(WIRE)
    sigma = entity_id("Organization", "Sigma Partners")
    hedged = [r for r in ie.relations if r.object_id == sigma]
    assert hedged and hedged[0].modality == "hedged"


def test_predicate_canonicalization() -> None:
    assert canonical_predicate("wired") == "TRANSFERRED"
    assert canonical_predicate("transfer") == "TRANSFERRED"
    assert canonical_predicate("nominee director of") == "DIRECTOR_OF"


def test_coref_coverage_not_double_counted() -> None:
    # One resolvable org-pronoun ("It") that also fills a relation subject slot must
    # be counted exactly once, not once per slot-resolution attempt.
    ie = run_ie("Acme Corp received funds. It transferred money to Beta Ltd.")
    assert ie.pronouns_total == 1
    assert ie.pronouns_resolved == 1


def test_coverage_counts_unresolvable_pronoun() -> None:
    # A leading pronoun with no antecedent counts toward total but not resolved.
    ie = run_ie("It transferred money to Beta Ltd.")
    assert ie.pronouns_total == 1
    assert ie.pronouns_resolved == 0


def test_extraction_is_deterministic() -> None:
    a = run_ie(WIRE)
    b = run_ie(WIRE)
    assert _rels(a) == _rels(b)
    assert [m.span.start for m in a.mentions] == [m.span.start for m in b.mentions]
