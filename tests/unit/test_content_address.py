from textgraph.core.content_address import (
    DOC_ID_PREFIX,
    blake3_hex,
    doc_id_for,
    verify_span_hash,
)


def test_blake3_hex_is_deterministic() -> None:
    assert blake3_hex(b"hello") == blake3_hex(b"hello")


def test_blake3_hex_differs_on_different_input() -> None:
    assert blake3_hex(b"hello") != blake3_hex(b"world")


def test_blake3_hex_empty_input() -> None:
    # Adversarial: empty document must hash, not crash.
    assert isinstance(blake3_hex(b""), str)
    assert len(blake3_hex(b"")) == 64


def test_doc_id_is_namespaced() -> None:
    did = doc_id_for(b"abc")
    assert did.startswith(DOC_ID_PREFIX)
    assert did == f"{DOC_ID_PREFIX}{blake3_hex(b'abc')}"


def test_verify_span_hash_roundtrip() -> None:
    raw = b"the quick brown fox"
    expected = blake3_hex(raw[4:9])
    assert verify_span_hash(raw, 4, 9, expected) is True


def test_verify_span_hash_rejects_tampered_hash() -> None:
    raw = b"the quick brown fox"
    assert verify_span_hash(raw, 4, 9, "deadbeef") is False


def test_verify_span_hash_rejects_out_of_range() -> None:
    raw = b"short"
    assert verify_span_hash(raw, 0, 999, blake3_hex(raw)) is False
    assert verify_span_hash(raw, 3, 1, blake3_hex(raw)) is False
