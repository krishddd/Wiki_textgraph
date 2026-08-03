from textgraph.l5_entity_resolution.blocking import candidate_pairs, cross_product
from textgraph.l5_entity_resolution.clustering import cluster
from textgraph.l5_entity_resolution.metrics import bcubed, blocking_recall, reduction_ratio
from textgraph.l5_entity_resolution.model import ERecord
from textgraph.l5_entity_resolution.scoring import score_pair
from textgraph.l5_entity_resolution.similarity import acronym, jaro_winkler, token_set_ratio


def _rec(eid: str, name: str, stripped: str, *, etype: str = "Organization", neigh=frozenset()):
    return ERecord(
        entity_id=eid,
        name=name,
        etype=etype,
        norm=name.lower(),
        stripped=stripped,
        acronym=acronym(name),
        mention_spans=(),
        neighbors=neigh,
    )


# --- similarity --------------------------------------------------------------
def test_jaro_winkler_bounds_and_prefix() -> None:
    assert jaro_winkler("acme", "acme") == 1.0
    assert jaro_winkler("", "acme") == 0.0
    assert jaro_winkler("acme corp", "acme corporation") > 0.8


def test_token_set_ratio() -> None:
    assert token_set_ratio("acme corp", "acme corp") == 1.0
    assert token_set_ratio("acme", "beta") == 0.0


def test_acronym() -> None:
    assert acronym("International Business Machines") == "ibm"
    assert acronym("Acme") == ""


# --- blocking ----------------------------------------------------------------
def test_blocking_groups_suffix_variants() -> None:
    recs = [
        _rec("a", "Acme Corp", "acme"),
        _rec("b", "Acme Corporation", "acme"),
        _rec("c", "Beta Ltd", "beta"),
    ]
    pairs = candidate_pairs(recs)
    assert ("a", "b") in pairs
    assert ("a", "c") not in pairs  # different block


def test_blocking_type_gated() -> None:
    recs = [_rec("a", "Acme", "acme"), _rec("p", "Acme", "acme", etype="Person")]
    assert candidate_pairs(recs) == []  # different types never compared


# --- scoring -----------------------------------------------------------------
def test_score_stripped_match_is_strong() -> None:
    assert score_pair(_rec("a", "Acme Corp", "acme"), _rec("b", "ACME", "acme")) >= 0.9


def test_score_relational_boost() -> None:
    base = score_pair(_rec("a", "Acme Group", "acme"), _rec("b", "Acme Inc", "acme"))
    boosted = score_pair(
        _rec("a", "Acme Group", "acme", neigh=frozenset({"x"})),
        _rec("b", "Acme Inc", "acme", neigh=frozenset({"x"})),
    )
    assert boosted >= base


# --- clustering: cohesion prevents chain over-merge --------------------------
def test_complete_linkage_blocks_chaining() -> None:
    a, b, c = _rec("A", "A", "a"), _rec("B", "B", "b"), _rec("C", "C", "c")
    by_id = {"A": a, "B": b, "C": c}
    scores = {("A", "B"): 0.9, ("B", "C"): 0.9, ("A", "C"): 0.5}

    def score_fn(x: ERecord, y: ERecord) -> float:
        key = tuple(sorted((x.entity_id, y.entity_id)))
        return scores.get(key, 1.0 if x.entity_id == y.entity_id else 0.0)

    groups = cluster(by_id, [("A", "B", 0.9), ("B", "C", 0.9)], score_fn, cohesion_min=0.86)
    # A~C is 0.5 < threshold, so A,B,C must NOT all merge (no galaxy-merge).
    assert all(len(g) <= 2 for g in groups)
    assert not any(set(g) == {"A", "B", "C"} for g in groups)


# --- metrics -----------------------------------------------------------------
def test_bcubed_perfect_and_over_merge() -> None:
    gold = {"a": "X", "b": "X", "c": "Y"}
    assert bcubed(gold, gold) == (1.0, 1.0, 1.0)
    over = {"a": "M", "b": "M", "c": "M"}  # everything merged
    precision, recall, _f1 = bcubed(over, gold)
    assert recall == 1.0 and precision < 1.0  # over-merge tanks precision, not recall


def test_blocking_recall_and_reduction() -> None:
    gold = {"a": "X", "b": "X", "c": "Y"}
    assert blocking_recall([("a", "b")], gold) == 1.0
    assert blocking_recall([], gold) == 0.0
    assert reduction_ratio(1, cross_product(3)) > 0.6
