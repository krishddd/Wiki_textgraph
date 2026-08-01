import pytest
from textgraph.core.canonical_json import canonical_dump_bytes, canonical_dumps


def test_keys_are_sorted() -> None:
    assert canonical_dumps({"b": 1, "a": 2}) == '{"a":2,"b":1}\n'


def test_nested_keys_are_sorted() -> None:
    out = canonical_dumps({"z": {"y": 1, "x": 2}})
    assert out == '{"z":{"x":2,"y":1}}\n'


def test_compact_separators() -> None:
    assert canonical_dumps([1, 2, 3]) == "[1,2,3]\n"


def test_trailing_newline() -> None:
    assert canonical_dumps({}).endswith("\n")


def test_non_ascii_preserved() -> None:
    # ensure_ascii=False keeps hashes stable and diffs readable.
    assert canonical_dumps({"k": "café"}) == '{"k":"café"}\n'


def test_bytes_are_utf8() -> None:
    assert canonical_dump_bytes({"k": "汉"}) == '{"k":"汉"}\n'.encode()


def test_dict_order_does_not_affect_output() -> None:
    # Byte-identical regardless of insertion order (G1).
    assert canonical_dumps({"a": 1, "b": 2}) == canonical_dumps({"b": 2, "a": 1})


def test_nan_is_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("nan")})
