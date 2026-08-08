"""Pinned build configuration + config hashing (G1).

Every layer is a pure function of the layer below it *plus a pinned config hash*.
The config captures the tool version, fixed random seeds, and the flags that alter
extraction (e.g. whether the opt-in LLM pass ran). Its hash is folded into
``manifest.json`` and can be compared across runs to explain any output change.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from textgraph import __version__
from textgraph.core.canonical_json import canonical_dump_bytes
from textgraph.core.content_address import blake3_hex


@dataclass(frozen=True)
class Config:
    """Immutable, hashable build configuration.

    Only fields that can change output belong here. Add fields as layers land; the
    hash then naturally distinguishes runs that used different settings.
    """

    tool_version: str = __version__
    # Fixed seeds for every stochastic step (Leiden, blocking, sampling). G1.
    seed: int = 0
    # Local-first by default: the LLM pass (L4) is opt-in (G2).
    llm_enabled: bool = False
    # Hierarchical chunking target (tokens); never fixed 512-token windows.
    chunk_target_tokens: int = 600
    # L2+L3 encoder IE: on by default; backend is the deterministic rule extractor
    # unless "gliner" is selected (requires the [ie] extra).
    extract_ie: bool = True
    ie_backend: str = "rules"
    # When ie_backend="gliner": prefer the int8-quantized ONNX model for CPU inference (a
    # large speedup over the fp32 torch path — GLiNER on CPU is otherwise minutes/chunk).
    # No effect on the default rules backend; quantization can shift GLiNER's logits, so it
    # is part of the config hash. Falls back to the torch weights if the ONNX file is absent.
    ie_onnx: bool = True
    # L5 entity resolution: link alias entities to a canonical node via SAME_AS.
    # Default rule backend is deterministic; "splink" requires the [er] extra.
    resolve_entities: bool = True
    er_backend: str = "rules"
    # Decision provenance: promote decision-worthy Rationale markers (WHY/DECISION/
    # RATIONALE/ADR-N) into first-class Decision nodes + causal edges. Depends only on
    # the L1 rationale spine (no IE/ER/L6/L8), deterministic, cited.
    derive_decisions: bool = True
    # L6 claim reification: turn each relation edge into a citable Claim node.
    reify_claims: bool = True
    # L6 bi-temporal assembly: close validity windows on superseded claims (invalidation
    # not deletion) using in-text dates only — no wall-clock, so graph.json stays stable.
    invalidate_claims: bool = True
    # Conflict detection: surface single-truth disagreements (same subject+predicate,
    # different objects, overlapping validity windows) as first-class Conflict nodes.
    # Detection only — never resolves/merges silently (G3). Deterministic.
    detect_conflicts: bool = True
    # Predicates treated as single-truth (only one object correct at a time) for conflict
    # detection. Multi-truth predicates (a company's several directors) are excluded.
    single_truth_predicates: tuple[str, ...] = ("BENEFICIAL_OWNER_OF", "CONTROLS", "DIRECTOR_OF")
    # Conflict resolution strategy (opt-in; "" = detection only, never resolve). One of
    # "most_recent" / "voting" / "credibility_weighted". Non-destructive: losing claims are
    # demoted (superseded_by + SUPERSEDED_BY edge), never deleted (G3).
    resolve_conflicts_strategy: str = ""
    # Per-source credibility (keyed by source_name) for the credibility_weighted strategy;
    # unset sources default to 1.0, so the strategy degrades gracefully to unweighted voting.
    source_credibility: dict[str, float] = field(default_factory=dict)
    # L7 graph analytics: PageRank/betweenness/communities folded into the graph,
    # contradictions surfaced as CONTRADICTS edges. Pure-Python deterministic default;
    # "leiden" (behind the [graph] extra) is the optional higher-quality community pass.
    analytics: bool = True
    analytics_backend: str = "builtin"
    # L8 retrieval: emit Chunk nodes + entity<->chunk links (the dual-node graph).
    emit_chunks: bool = True
    # Phase 8 vision-native retrieval: multi-vector page embedder for MaxSim late
    # interaction. "hash" is the deterministic, CI-safe default; "colpali" is the opt-in
    # [vision] model (import-guarded, falls back to hash). Query-time only — no effect on
    # graph.json, so the default install is unaffected.
    vision_backend: str = "hash"
    vision_model: str = ""
    vision_dim: int = 48
    # Phase 9 enterprise FGAC: authorization backend for the (query-time) access guard.
    # "rebac" is the deterministic, dependency-free default; "openfga" is the opt-in
    # [security] Zanzibar service (import-guarded, falls back to rebac). Access control is
    # query-time only, so it never touches graph.json — the default install is unaffected.
    security_backend: str = "rebac"
    # L4 optional LLM (Phase 6): synthesizes GENERATED community summaries. Off by
    # default (G2) so the determinism gate never sees an LLM. The model id + base URL
    # affect output, so they belong in the config hash; the API key never does — it is
    # read from the environment only and must not leak into config_hash/manifest.
    llm_model: str = ""
    llm_base_url: str = ""
    llm_max_calls: int = 8  # hard budget on LLM calls per build (G7)
    llm_max_tokens: int = 256
    llm_temperature: float = 0.0  # deterministic-leaning; responses are also cached
    # Free-form, pinned model ids per layer (filled in as layers are added).
    model_pins: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        """Deterministic blake3 hash of the canonical-JSON form of this config."""
        return blake3_hex(canonical_dump_bytes(self.to_dict()))
