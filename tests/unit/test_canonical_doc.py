from textgraph.core.canonical_doc import CanonicalDoc, normalize
from textgraph.core.content_address import blake3_hex, doc_id_for


def test_normalize_plain_ascii() -> None:
    text, m = normalize(b"hello")
    assert text == "hello"
    assert m.to_raw_span(0, 5) == (0, 5)


def test_normalize_collapses_crlf() -> None:
    text, m = normalize(b"a\r\nb")
    assert text == "a\nb"
    # The whole canonical string maps back to all raw bytes.
    assert m.to_raw_span(0, len(text)) == (0, 4)


def test_normalize_collapses_lone_cr() -> None:
    text, _ = normalize(b"a\rb")
    assert text == "a\nb"


def test_normalize_strips_bom() -> None:
    raw = "﻿title".encode()
    text, m = normalize(raw)
    assert text == "title"
    # 't' (canonical index 0) starts after the 3-byte UTF-8 BOM.
    assert m.to_raw(0) == 3


def test_normalize_empty_doc() -> None:
    # Adversarial: empty document degrades gracefully.
    text, m = normalize(b"")
    assert text == ""
    assert m.to_raw_span(0, 0) == (0, 0)


def test_from_bytes_sets_content_addressed_id() -> None:
    raw = b"content"
    doc = CanonicalDoc.from_bytes(raw, source_name="a.txt")
    assert doc.doc_id == doc_id_for(raw)
    assert doc.raw_len == len(raw)
    assert doc.source_name == "a.txt"


def test_span_hash_matches_raw_slice() -> None:
    raw = "aé汉 word".encode()  # mixed-width; provenance must survive multibyte
    doc = CanonicalDoc.from_bytes(raw)
    # canonical text equals decoded text here (no CRLF/BOM), so char indices align.
    start, end = 0, 3  # "aé汉"
    b0, b1 = doc.raw_span(start, end)
    assert doc.span_hash(raw, start, end) == blake3_hex(raw[b0:b1])


def test_single_token_doc() -> None:
    doc = CanonicalDoc.from_bytes(b"x")
    assert doc.text == "x"
    assert doc.raw_span(0, 1) == (0, 1)
