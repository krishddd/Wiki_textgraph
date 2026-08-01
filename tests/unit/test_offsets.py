import pytest
from textgraph.core.offsets import OffsetMap


def test_ascii_identity_mapping() -> None:
    # "abc": 3 one-byte chars.
    m = OffsetMap.from_char_byte_lengths([1, 1, 1], raw_len=3)
    assert [m.to_raw(i) for i in range(4)] == [0, 1, 2, 3]
    # Compact: a single run for uniform ASCII.
    assert len(m.runs) == 1


def test_multibyte_mapping() -> None:
    # "aé汉": 1-byte + 2-byte + 3-byte.
    m = OffsetMap.from_char_byte_lengths([1, 2, 3], raw_len=6)
    assert m.to_raw(0) == 0
    assert m.to_raw(1) == 1
    assert m.to_raw(2) == 3
    assert m.to_raw(3) == 6  # exclusive end maps to raw_len


def test_crlf_collapse_run() -> None:
    # canonical "a\nb" from raw "a\r\nb": '\n' consumed 2 raw bytes.
    m = OffsetMap.from_char_byte_lengths([1, 2, 1], raw_len=4)
    assert m.to_raw_span(0, 3) == (0, 4)
    assert m.to_raw_span(1, 2) == (1, 3)  # the newline spans raw \r\n


def test_empty_map() -> None:
    m = OffsetMap.from_char_byte_lengths([], raw_len=0)
    assert m.to_raw(0) == 0
    assert m.to_raw_span(0, 0) == (0, 0)


def test_out_of_range_raises() -> None:
    m = OffsetMap.from_char_byte_lengths([1, 1], raw_len=2)
    with pytest.raises(IndexError):
        m.to_raw(3)
    with pytest.raises(IndexError):
        m.to_raw(-1)


def test_span_start_after_end_raises() -> None:
    m = OffsetMap.from_char_byte_lengths([1, 1], raw_len=2)
    with pytest.raises(ValueError):
        m.to_raw_span(2, 1)


def test_serialization_roundtrip() -> None:
    m = OffsetMap.from_char_byte_lengths([1, 2, 3, 1, 1], raw_len=8)
    restored = OffsetMap.from_dict(m.to_dict())
    assert restored == m
    assert [restored.to_raw(i) for i in range(6)] == [m.to_raw(i) for i in range(6)]
