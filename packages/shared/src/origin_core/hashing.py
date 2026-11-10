"""Content hashing and canonical serialisation used for cache keys and evidence integrity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    """Serialise to JSON with sorted keys and no insignificant whitespace.

    Two structurally equal values always produce identical bytes, so the hash of the
    output is a stable key.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def request_hash(provider: str, asset_sha256: str, params: dict[str, Any]) -> str:
    """Key for one provider query: the provider, the exact image bytes and the parameters."""
    payload = {"provider": provider, "asset": asset_sha256, "params": params}
    return sha256_hex(canonical_json(payload))
