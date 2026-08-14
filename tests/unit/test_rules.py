"""Forward-chaining Datalog rule engine (L-reasoning) + engine wiring."""

from textgraph.l8_retrieval.engine import QueryEngine
from textgraph.reasoning.rules import Pattern, Rule, forward_chain, parse_rules
from textgraph.store.base import ConfidenceTag, Edge, Node


def _rel(a: str, pred: str, b: str) -> Edge:
    return Edge(
        edge_id=f"edge:{a}:{pred}:{b}",
        subject=a,
        predicate=pred,
        object=b,
        tag=ConfidenceTag.EXTRACTED,
        confidence=0.9,
    )


def test_transitive_closure_reaches_fixpoint() -> None:
    facts = [("CONTROLS", "a", "b"), ("CONTROLS", "b", "c"), ("CONTROLS", "c", "d")]
    rules = parse_rules("CONTROLS(X, Z) :- CONTROLS(X, Y), CONTROLS(Y, Z).")
    derived, _ = forward_chain(facts, rules)
    assert ("CONTROLS", "a", "c") in derived
    assert ("CONTROLS", "a", "d") in derived  # multi-hop closure
    assert ("CONTROLS", "b", "d") in derived


def test_join_across_two_predicates_with_provenance() -> None:
    facts = [("BROTHER", "bob", "sam"), ("PARENT", "sam", "kid")]
    rules = parse_rules("UNCLE(A, C) :- BROTHER(A, B), PARENT(B, C).")
    derived, derivations = forward_chain(facts, rules)
    assert ("UNCLE", "bob", "kid") in derived
    d = derivations[("UNCLE", "bob", "kid")]
    assert d.rule_id == "r1"
    assert set(d.support) == {("BROTHER", "bob", "sam"), ("PARENT", "sam", "kid")}


def test_parse_distinguishes_variables_from_constants() -> None:
    (rule,) = parse_rules('OWNS(X, "Acme Corp") :- CONTROLS(X, y).')
    assert rule.head == Pattern("OWNS", "?X", "Acme Corp")  # uppercase var, quoted constant
    assert rule.body == (Pattern("CONTROLS", "?X", "y"),)  # lowercase constant stays constant


def test_unsafe_head_variable_is_not_derived() -> None:
    # Z appears in the head but nowhere in the body -> unbound -> no fact is invented.
    facts = [("KNOWS", "a", "b")]
    rules = [Rule("r1", (Pattern("KNOWS", "?X", "?Y"),), Pattern("REL", "?X", "?Z"))]
    derived, _ = forward_chain(facts, rules)
    assert derived == []


def test_cycle_terminates() -> None:
    facts = [("LINK", "a", "b"), ("LINK", "b", "a")]
    rules = parse_rules("LINK(X, Z) :- LINK(X, Y), LINK(Y, Z).")
    derived, _ = forward_chain(facts, rules)  # must not hang
    assert ("LINK", "a", "a") in derived and ("LINK", "b", "b") in derived


def test_engine_apply_rules_returns_named_new_facts() -> None:
    nodes = [Node(f"entity:{x}", ("Entity",), {"name": x.title()}) for x in ("a", "b", "c")]
    edges = [_rel("entity:a", "CONTROLS", "entity:b"), _rel("entity:b", "CONTROLS", "entity:c")]
    out = QueryEngine(nodes, edges).apply_rules("CONTROLS(X, Z) :- CONTROLS(X, Y), CONTROLS(Y, Z).")
    assert len(out) == 1  # only the NEW fact a->c (base a->b, b->c excluded)
    fact = out[0]
    assert (fact["source_name"], fact["predicate"], fact["target_name"]) == ("A", "CONTROLS", "C")
    assert fact["support"]  # explainable
