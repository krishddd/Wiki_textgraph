"""L6 — graph model / claim reification.

Turns extracted relation edges into first-class ``Claim`` nodes with a temporal
validity window, so assertions can be cited, explained, and compared for
contradiction. Deterministic and model-free; see :mod:`textgraph.l6_graph_model.claims`.
"""

from textgraph.l6_graph_model.claims import claim_id_for, is_relation_edge, reify_claims
from textgraph.l6_graph_model.temporal import apply_temporal

__all__ = ["apply_temporal", "claim_id_for", "is_relation_edge", "reify_claims"]
