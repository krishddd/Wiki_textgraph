"""Phase 9 unit tests: ReBAC reachability, ABAC conditions, policy assembly, fallback."""

from textgraph.core.config import Config
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.security import (
    IpAllowlist,
    MinClearance,
    RebacStore,
    RelationTuple,
    SecurityContext,
    SecurityPolicy,
    TimeWindow,
    policy_from_dict,
    resolve_policy_engine,
)
from textgraph.security.abac import AbacRule
from textgraph.security.policy import _openfga_backend


def _store(*tuples: tuple[str, str, str]) -> RebacStore:
    return RebacStore(RelationTuple(*t) for t in tuples)


def test_rebac_direct_and_owner_implies_viewer() -> None:
    store = _store(("doc:d1", "viewer", "user:alice"), ("doc:d2", "owner", "user:bob"))
    assert store.check(["user:alice"], "doc:d1")
    assert store.check(["user:bob"], "doc:d2")  # owner => viewer
    assert not store.check(["user:alice"], "doc:d2")
    assert not store.check(["user:eve"], "doc:d1")


def test_rebac_group_membership_and_nesting() -> None:
    store = _store(
        ("group:leads", "member", "user:alice"),
        ("group:staff", "member", "group:leads"),  # nested group
        ("doc:d1", "viewer", "group:staff"),
    )
    assert store.check(["user:alice"], "doc:d1")  # alice -> leads -> staff -> viewer
    assert not store.check(["user:carol"], "doc:d1")


def test_rebac_parent_inheritance_and_userset() -> None:
    store = _store(
        ("folder:cases", "viewer", "user:alice"),
        ("doc:d1", "parent", "folder:cases"),  # inherit viewer from the folder
        ("doc:d2", "viewer", "folder:cases#viewer"),  # userset rewrite
    )
    assert store.check(["user:alice"], "doc:d1")
    assert store.check(["user:alice"], "doc:d2")


def test_rebac_cyclic_policy_terminates() -> None:
    # parent cycle must not loop forever; it simply grants nothing.
    store = _store(("doc:a", "parent", "doc:b"), ("doc:b", "parent", "doc:a"))
    assert not store.check(["user:alice"], "doc:a")


def test_abac_min_clearance() -> None:
    rule = MinClearance({"secret": 3, "public": 0})
    assert rule.allows(SecurityContext("a", clearance=3), {"classification": "secret"})
    assert not rule.allows(SecurityContext("a", clearance=2), {"classification": "secret"})
    assert rule.allows(SecurityContext("a", clearance=0), {"classification": "public"})
    assert rule.allows(SecurityContext("a", clearance=0), {})  # unlabelled => public


def test_abac_min_clearance_fails_closed_on_unmapped_label() -> None:
    # A resource classified with a label not in the map must be DENIED (never silently
    # treated as public), even for a maximally-cleared principal.
    rule = MinClearance({"secret": 3})
    assert not rule.allows(SecurityContext("a", clearance=99), {"classification": "topsecret"})
    assert rule.allows(SecurityContext("a", clearance=0), {"classification": ""})  # unclassified


def test_abac_ip_allowlist() -> None:
    rule = IpAllowlist(("10.0.", "192.168."))
    assert rule.allows(SecurityContext("a", ip="10.0.0.5"), {})
    assert not rule.allows(SecurityContext("a", ip="8.8.8.8"), {})
    assert not rule.allows(SecurityContext("a"), {})  # no ip presented, list is set
    assert IpAllowlist().allows(SecurityContext("a"), {})  # empty list allows all


def test_abac_time_window() -> None:
    rule = TimeWindow(not_before="2026-01-01", not_after="2026-12-31")
    assert rule.allows(SecurityContext("a", as_of="2026-06-15"), {})
    assert not rule.allows(SecurityContext("a", as_of="2025-12-31"), {})
    assert not rule.allows(SecurityContext("a", as_of="2027-01-01"), {})
    assert not rule.allows(SecurityContext("a"), {})  # must state when
    assert TimeWindow().allows(SecurityContext("a"), {})  # no bounds => allow


def test_abac_is_anded_across_rules() -> None:
    policy = SecurityPolicy(
        rebac=_store(("doc:d1", "viewer", "user:alice")),
        abac=(MinClearance({"secret": 3}),),
        doc_attributes={"d1": {"classification": "secret"}},
    )
    assert policy.can_read_doc(SecurityContext("alice", clearance=3), "d1")
    assert not policy.can_read_doc(SecurityContext("alice", clearance=1), "d1")  # ReBAC ok, ABAC no


def test_authorized_docs_is_the_readable_subset() -> None:
    policy = SecurityPolicy(rebac=_store(("doc:d1", "viewer", "user:alice")))
    got = policy.authorized_docs(SecurityContext("alice"), ["d1", "d2", "d3"])
    assert got == frozenset({"d1"})


def test_policy_from_dict_builds_rebac_and_abac() -> None:
    policy = policy_from_dict(
        {
            "tuples": [["doc:d1", "viewer", "user:alice"]],
            "min_clearance": {"secret": 5},
            "ip_allowlist": ["10.0."],
            "time_window": {"not_before": "2026-01-01"},
            "doc_attributes": {"d1": {"classification": "secret"}},
        }
    )
    assert len(policy.abac) == 3
    assert all(isinstance(r, AbacRule) for r in policy.abac)
    ctx = SecurityContext("alice", clearance=5, ip="10.0.0.1", as_of="2026-06-01")
    assert policy.can_read_doc(ctx, "d1")
    assert not policy.can_read_doc(SecurityContext("alice", clearance=5, ip="8.8.8.8"), "d1")


def test_resolve_policy_engine_falls_back_without_security_extra() -> None:
    # [security] (openfga-sdk) isn't installed in CI: 'openfga' must degrade to 'rebac'.
    assert resolve_policy_engine(Config(security_backend="openfga")) == "rebac"
    assert resolve_policy_engine(Config()) == "rebac"


def test_openfga_backend_raises_unsupported_without_extra() -> None:
    try:
        import openfga_sdk  # noqa: F401
    except ImportError:
        import pytest

        with pytest.raises(UnsupportedFormat, match="security"):
            _openfga_backend(Config(security_backend="openfga"))
