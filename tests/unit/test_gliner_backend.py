"""Sprint 1.3 tests: the GLiNER backend's testable seams (ONNX path is [ie]-only).

The model-loading + NER lines require the ``[ie]`` extra and a downloaded model, so they
are not exercised in the lean CI. What *is* pure and testable — the prediction→mention
mapping, availability probe, and clean fallback — is covered here.
"""

from textgraph.core.config import Config
from textgraph.l0_ingest.base import UnsupportedFormat
from textgraph.l3_encoder_ie import gliner_backend as gb


def test_ie_onnx_is_on_by_default() -> None:
    # The CPU-speed fix (int8 ONNX) is the default when the GLiNER backend is used.
    assert Config().ie_onnx is True


def test_mentions_from_predictions_maps_offsets_and_filters() -> None:
    preds = [
        {"start": 20, "end": 28, "label": "Person", "text": "John Doe"},
        {"start": 0, "end": 9, "label": "Organization", "text": "Acme Corp"},
        {"start": 5, "end": 8, "label": "Nonsense", "text": "xyz"},  # unknown label -> dropped
    ]
    ms = gb.mentions_from_predictions(preds)
    assert [m.etype for m in ms] == ["Organization", "Person"]  # sorted by span; unknown gone
    assert ms[0].text == "Acme Corp" and ms[0].span.start == 0 and ms[0].span.end == 9
    assert ms[0].norm  # normalized surface is populated


def test_backend_falls_back_cleanly_without_the_extra() -> None:
    # In the lean CI, gliner isn't installed: is_available() is False and the extractor
    # raises UnsupportedFormat, which the pipeline turns into a rule-backend fallback.
    if not gb.is_available():
        assert gb.is_available() is False
        try:
            gb.extract_document_gliner("Acme Corp controls Beta Ltd.")
        except UnsupportedFormat as exc:
            assert "ie" in str(exc)
        else:  # pragma: no cover - only if [ie] is somehow installed in CI
            raise AssertionError("expected UnsupportedFormat without the [ie] extra")
