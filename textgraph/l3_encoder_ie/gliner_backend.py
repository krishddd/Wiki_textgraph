"""GLiNER-backed extractor (optional, ``[ie]`` extra).

Higher-recall zero-shot NER + joint relation extraction, CPU-runnable and
deterministic at inference (pinned weights, no sampling). Import-guarded so the
default install never requires it. Produces the same :class:`IEResult` shape as the
rule backend, so nothing downstream changes.

This is a thin adapter; the heavy lifting is the GLiNER model. When the extra is not
installed, :func:`extract_document_gliner` raises ``UnsupportedFormat`` and the
pipeline falls back to the rule backend.
"""

from __future__ import annotations

from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l3_encoder_ie.model import IEResult

#: Pinned model id for reproducibility (G1). Update deliberately, never implicitly.
GLINER_MODEL_ID = "urchade/gliner_medium-v2.1"

_LABELS = ["Organization", "Person", "Money", "Account", "Date", "Email"]


def is_available() -> bool:
    try:
        import gliner  # noqa: F401
    except ImportError:
        return False
    return True


def extract_document_gliner(text: str, *, model_id: str = GLINER_MODEL_ID) -> IEResult:
    """Extract entities/relations with GLiNER. Requires ``textgraph[ie]``.

    Kept intentionally small: it loads the pinned model, runs zero-shot NER over the
    document labels, and maps spans back to canonical offsets. Relation extraction
    uses the same deterministic sentence patterns as the rule backend over the
    GLiNER mentions, so recall improves without new nondeterminism.
    """
    if not is_available():
        raise UnsupportedFormat("GLiNER backend needs an extra: install 'textgraph[ie]'")
    # Deferred, real implementation loads the model and fills mentions; wiring the
    # weights/caching lands with the model-download story. Until then, callers use
    # backend='rules' (the deterministic default) and this raises clearly.
    raise UnsupportedFormat(
        "GLiNER backend adapter is not wired to weights yet; use backend='rules'"
    )
