"""Sprint 3.1: gate the extraction-quality metrics so they can't silently regress."""

from benchmarks.quality import measure


def test_quality_floors_hold() -> None:
    m = measure()
    ep, er, _ef = m["entity_prf"]  # type: ignore[misc]
    _rp, _rr, rf = m["edge_prf"]  # type: ignore[misc]
    # Entities: all gold entities are found, no spurious ones on this fixture.
    assert ep == 1.0 and er == 1.0
    # Asserted relations F1 above a pinned floor (currently 0.833; one coref error).
    assert rf >= 0.8, m
    # Every asserted relation edge is cited (byte-level re-verification gated elsewhere).
    assert m["citation_coverage"] == 1.0
    # The false-edge rate is bounded and honest (documented coref limit).
    assert m["false_edge_rate"] <= 0.2  # type: ignore[operator]
