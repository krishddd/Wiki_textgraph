"""L2 — Linguistic Substrate.

Deterministic, model-free sentence segmentation, coreference-lite, and
negation/modality detection that support L3 extraction. Higher-quality statistical
components (spaCy/Stanza, fastcoref, HeidelTime) attach behind the ``[ie]`` extra.
See ARCHITECTURE.md.
"""

from textgraph.l2_linguistic.negation import modality, polarity
from textgraph.l2_linguistic.sentences import segment

__all__ = ["modality", "polarity", "segment"]
