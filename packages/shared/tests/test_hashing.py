import math

import pytest

from origin_core.hashing import canonical_json, request_hash, sha256_hex


def test_sha256_hex_known_vector() -> None:
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_hex(b"abc") == expected


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [1, 2]}) == canonical_json({"a": [1, 2], "b": 1})
    assert canonical_json({"a": "é"}) == '{"a":"é"}'.encode()


def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})


def test_request_hash_changes_with_each_input() -> None:
    base = request_hash("lens", "aa", {"type": "exact_matches"})
    assert base == request_hash("lens", "aa", {"type": "exact_matches"})
    assert base != request_hash("vision", "aa", {"type": "exact_matches"})
    assert base != request_hash("lens", "bb", {"type": "exact_matches"})
    assert base != request_hash("lens", "aa", {"type": "all"})
