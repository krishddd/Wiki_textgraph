"""Vision-native, late-interaction retrieval (Phase 8, `[vision]` extra for the model).

The MaxSim operator + multi-vector embedders + page retriever that bring ColPali-style
visual document retrieval to TextGraph. Pure-Python and deterministic by default (the
model is opt-in behind ``[vision]``); it only ever operates on vectors, so ``graph.json``
is untouched. See :mod:`textgraph.l8_retrieval.vision.maxsim`.
"""

from textgraph.l8_retrieval.vision.embed import Embedder, HashEmbedder, resolve_embedder
from textgraph.l8_retrieval.vision.maxsim import maxsim
from textgraph.l8_retrieval.vision.retriever import VisionPage, VisionRetriever

__all__ = [
    "Embedder",
    "HashEmbedder",
    "VisionPage",
    "VisionRetriever",
    "maxsim",
    "resolve_embedder",
]
