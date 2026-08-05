"""The security policy: ReBAC relations + ABAC conditions over documents (Phase 9).

A :class:`SecurityPolicy` binds the two authorization models of the gap analysis (§3.1)
to the unit TextGraph actually governs — the **source document**. Every node and edge in
the graph is provenance-linked to the documents it was extracted from, so document-level
authorization is exactly the right granularity: a node is visible to a principal iff the
principal may read a document it derives from *and* that document passes the ABAC
conditions. Enforcement of this policy inside traversal (so unauthorized nodes get a zero
transition probability rather than being filtered out afterwards) lives in
:class:`~textgraph.l8_retrieval.engine.QueryEngine`; this module only decides, per
principal, which documents are authorized.

The deterministic ReBAC store is the default. A real OpenFGA/Zanzibar service is opt-in
behind the ``[security]`` extra via :func:`resolve_policy_engine`, import-guarded with a
clean fallback — the same upgrade-or-fall-back rule as GLiNER / Splink / ColPali.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from textgraph.core.config import Config
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.security.abac import AbacRule, IpAllowlist, MinClearance, TimeWindow
from textgraph.security.context import SecurityContext
from textgraph.security.rebac import RebacStore, RelationTuple


@dataclass(frozen=True)
class SecurityPolicy:
    """A document-level authorization decision procedure (ReBAC AND ABAC)."""

    rebac: RebacStore = field(default_factory=RebacStore)
    abac: tuple[AbacRule, ...] = ()
    # doc_id -> attributes evaluated by ABAC rules (e.g. {"classification": "secret"}).
    doc_attributes: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def can_read_doc(self, context: SecurityContext, doc_id: str) -> bool:
        """True iff the principal may read ``doc_id`` under both ReBAC and ABAC."""
        if not self.rebac.check(context.subjects(), f"doc:{doc_id}"):
            return False
        attrs = self.doc_attributes.get(doc_id, {})
        return all(rule.allows(context, attrs) for rule in self.abac)

    def authorized_docs(self, context: SecurityContext, all_docs: Iterable[str]) -> frozenset[str]:
        """The subset of ``all_docs`` the principal may read (sorted-stable, deterministic)."""
        return frozenset(d for d in sorted(set(all_docs)) if self.can_read_doc(context, d))


def policy_from_dict(spec: Mapping[str, object]) -> SecurityPolicy:
    """Build a :class:`SecurityPolicy` from a plain dict (the JSON policy file format).

    ``{"tuples": [[object, relation, subject], ...],
       "min_clearance": {label: level, ...},
       "ip_allowlist": [prefix, ...],
       "time_window": {"not_before": iso, "not_after": iso},
       "doc_attributes": {doc_id: {attr: value}}}`` — every field optional.
    """
    raw_tuples = spec.get("tuples", [])
    tuples: list[RelationTuple] = []
    if isinstance(raw_tuples, list):
        for t in raw_tuples:
            if isinstance(t, list | tuple) and len(t) == 3:
                tuples.append(RelationTuple(str(t[0]), str(t[1]), str(t[2])))
    abac: list[AbacRule] = []
    clearance = spec.get("min_clearance")
    if isinstance(clearance, Mapping):
        abac.append(MinClearance({str(k): int(v) for k, v in clearance.items()}))
    ip = spec.get("ip_allowlist")
    if isinstance(ip, list) and ip:
        abac.append(IpAllowlist(tuple(str(p) for p in ip)))
    window = spec.get("time_window")
    if isinstance(window, Mapping):
        abac.append(
            TimeWindow(
                not_before=_opt_str(window.get("not_before")),
                not_after=_opt_str(window.get("not_after")),
            )
        )
    doc_attrs_raw = spec.get("doc_attributes", {})
    doc_attrs: dict[str, dict[str, str]] = {}
    if isinstance(doc_attrs_raw, Mapping):
        for doc, attrs in doc_attrs_raw.items():
            if isinstance(attrs, Mapping):
                doc_attrs[str(doc)] = {str(k): str(v) for k, v in attrs.items()}
    return SecurityPolicy(rebac=RebacStore(tuples), abac=tuple(abac), doc_attributes=doc_attrs)


def _opt_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) else None


def resolve_policy_engine(config: Config) -> str:
    """Return the active policy backend name, falling back to the deterministic default.

    ``security_backend='openfga'`` requests the Zanzibar service; if the ``[security]``
    extra (``openfga-sdk``) is not installed we fall back to the built-in ``RebacStore``
    rather than failing — the same import-guard pattern used across the project.
    """
    if config.security_backend == "openfga":
        try:
            return _openfga_backend(config)
        except UnsupportedFormat:
            pass
    return "rebac"


def _openfga_backend(config: Config) -> str:  # pragma: no cover - needs [security]
    """Probe for the OpenFGA SDK (behind the ``[security]`` extra)."""
    try:
        import openfga_sdk  # noqa: F401
    except ImportError as exc:
        raise UnsupportedFormat(
            "security_backend='openfga' requires the [security] extra (openfga-sdk)"
        ) from exc
    # A real implementation would open an OpenFGA client here and delegate check() calls to
    # the Zanzibar store. Kept behind the guard so the default path needs no service.
    raise UnsupportedFormat("OpenFGA backend is not wired in this build; using 'rebac'")
