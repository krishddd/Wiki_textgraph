"""GLiNER-backed extractor (optional, ``[ie]`` extra).

Higher-recall zero-shot NER, CPU-runnable and deterministic at inference (pinned weights,
no sampling). Import-guarded so the default install never requires it; when the extra is
absent, :func:`extract_document_gliner` raises ``UnsupportedFormat`` and the pipeline falls
back to the rule backend.

**CPU performance — int8 ONNX.** GLiNER on CPU via the fp32 torch path is painfully slow
(minutes per handful of chunks). :func:`load_model` therefore loads the **int8-quantized
ONNX** model by default (a large CPU speedup), falling back to the torch weights only if the
ONNX file isn't published for the pinned model. This is the whole point of the ``ie_onnx``
config knob.

**Reuse, not reinvention.** GLiNER supplies only the *mentions* (NER); relations are then
built by the exact same deterministic extractor the rule backend uses
(:func:`~textgraph.l3_encoder_ie.extract.assemble_ie`), so recall improves without adding
any new nondeterminism, and the ``IEResult`` shape is identical.

CI note: the lean CI does not install ``[ie]`` or download a model, so the model-loading and
NER lines here are ``# pragma: no cover`` and are validated on a machine with the extra. The
pure pieces — the mention mapping, availability check, and fallback — are unit-tested.
"""

from __future__ import annotations

from typing import Any

from textgraph.core.layout import Block, Span
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l3_encoder_ie.canonicalize import normalize_name
from textgraph.l3_encoder_ie.extract import _prose_units, assemble_ie
from textgraph.l3_encoder_ie.model import IEResult, Mention

#: Pinned model id for reproducibility (G1). Update deliberately, never implicitly.
GLINER_MODEL_ID = "urchade/gliner_medium-v2.1"
#: The int8-quantized ONNX weights file within the model repo (CPU-fast path).
GLINER_ONNX_FILE = "onnx/model_quantized.onnx"

_LABELS = ["Organization", "Person", "Money", "Account", "Date", "Email"]


def is_available() -> bool:
    try:
        import gliner  # noqa: F401
    except ImportError:
        return False
    return True


def load_model(
    *, model_id: str = GLINER_MODEL_ID, use_onnx: bool = True
) -> Any:  # pragma: no cover
    """Load the pinned GLiNER model, preferring the int8-quantized ONNX runtime on CPU."""
    from gliner import GLiNER

    if use_onnx:
        try:
            return GLiNER.from_pretrained(
                model_id,
                load_onnx_model=True,
                load_tokenizer=True,
                onnx_model_file=GLINER_ONNX_FILE,
            )
        except Exception:
            # The quantized ONNX file may not be published for this model — fall back to
            # the torch weights rather than fail (still deterministic, just slower).
            pass
    return GLiNER.from_pretrained(model_id)


def mentions_from_predictions(predictions: list[dict[str, Any]]) -> list[Mention]:
    """Map GLiNER's char-offset predictions to sorted canonical :class:`Mention`s (pure).

    GLiNER's ``predict_entities`` returns ``[{"start", "end", "label", "text"}]`` with
    offsets into the *input* text — which is our canonical document text — so the spans are
    already canonical. Predictions with an unknown label are dropped; ties break
    deterministically by span then type.
    """
    mentions: list[Mention] = []
    for p in predictions:
        label = str(p.get("label", ""))
        if label not in _LABELS:
            continue
        surface = str(p.get("text", ""))
        span = Span(int(p["start"]), int(p["end"]))
        mentions.append(Mention(text=surface, etype=label, span=span, norm=normalize_name(surface)))
    mentions.sort(key=lambda m: (m.span.start, m.span.end, m.etype))
    return mentions


def extract_document_gliner(
    text: str,
    *,
    blocks: list[Block] | None = None,
    model_id: str = GLINER_MODEL_ID,
    use_onnx: bool = True,
) -> IEResult:
    """Extract entities/relations with GLiNER NER + the shared deterministic relation pass.

    Requires ``textgraph[ie]``; raises ``UnsupportedFormat`` (→ rule-backend fallback) if the
    model isn't installed.
    """
    if not is_available():
        raise UnsupportedFormat("GLiNER backend needs an extra: install 'textgraph[ie]'")
    model = load_model(model_id=model_id, use_onnx=use_onnx)  # pragma: no cover - needs [ie]
    predictions = model.predict_entities(text, _LABELS)  # pragma: no cover - needs [ie]
    mentions = mentions_from_predictions(predictions)  # pragma: no cover - needs [ie]
    block_spans = [span for span, _ in _prose_units(text, blocks)]  # pragma: no cover
    return assemble_ie(text, block_spans, mentions)  # pragma: no cover - needs [ie]
