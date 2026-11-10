"""Content Credentials (C2PA): read the manifest store and decide how far to trust it.

Three states, as the plan requires:

* `none`              no C2PA manifest in the file;
* `present_untrusted` a manifest exists but is not both valid and from a trusted signer:
                      the signer is not on the trust list, or the signature or content
                      hash fails. The raw validation state ("Valid", "Invalid") and failure
                      codes are kept, so an invalid manifest is never shown as merely
                      untrusted;
* `valid_trusted`     the signature validates and chains to an anchor on the trust list.

A valid signature is not the same as a trusted signer, and neither proves the picture is
truthful: C2PA records who signed what, and when. The signed time becomes a dating signal.

The trust list is the official C2PA list, pinned and hash-checked (see trust/SOURCE.md).
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import c2pa  # pyright: ignore[reportMissingTypeStubs]

from origin_core.enums import C2PAState
from origin_core.hashing import sha256_hex

TRUST_DIR = Path(__file__).with_name("trust")
TRUST_LIST_FILE = TRUST_DIR / "C2PA-TRUST-LIST.pem"
TRUST_LIST_COMMIT = "64b3f9c8ebb95d2b73557aea25172d694db67c1e"
TRUST_LIST_SHA256 = "148c1c167e98dc909a0d5793d2feee1022aa60fef5c83a0d6b08f67f4446bc37"
TRUST_LIST_ID = f"c2pa-trust-list@{TRUST_LIST_COMMIT[:7]}"


class TrustListError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrustAnchors:
    pem: str
    #: Identifies the anchors used, recorded with every result.
    id: str


@dataclass(frozen=True)
class C2PAResult:
    state: C2PAState
    trust_list: str
    validation_state: str | None = None
    failures: list[str] = field(default_factory=list[str])
    signer_issuer: str | None = None
    signer_common_name: str | None = None
    signed_at: datetime | None = None
    claim_generator: str | None = None
    title: str | None = None
    actions: list[str] = field(default_factory=list[str])
    manifest_store: dict[str, Any] | None = None
    error: str | None = None


@lru_cache(maxsize=1)
def official_trust_anchors() -> TrustAnchors:
    data = TRUST_LIST_FILE.read_bytes()
    actual = sha256_hex(data)
    if actual != TRUST_LIST_SHA256:
        raise TrustListError(
            f"{TRUST_LIST_FILE.name} has SHA-256 {actual}, expected {TRUST_LIST_SHA256}; "
            "update the pinned values deliberately (see trust/SOURCE.md)"
        )
    return TrustAnchors(pem=data.decode("ascii"), id=TRUST_LIST_ID)


def with_extra_anchors(base: TrustAnchors, extra_pem: str, label: str) -> TrustAnchors:
    """Add anchors (e.g. an organisation's own CA, or a test root) to a trust set."""
    return TrustAnchors(
        pem=base.pem.rstrip() + "\n" + extra_pem.strip() + "\n", id=f"{base.id}+{label}"
    )


def _context(anchors: TrustAnchors) -> Any:
    settings = c2pa.Settings.from_dict(  # pyright: ignore[reportUnknownMemberType]
        {"verify": {"verify_trust": True}, "trust": {"trust_anchors": anchors.pem}}
    )
    return c2pa.Context(settings)  # pyright: ignore[reportUnknownMemberType]


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _actions(manifest: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for assertion in cast(list[dict[str, Any]], manifest.get("assertions") or []):
        if str(assertion.get("label", "")).startswith("c2pa.actions"):
            data = cast(dict[str, Any], assertion.get("data") or {})
            for action in cast(list[dict[str, Any]], data.get("actions") or []):
                if "action" in action:
                    found.append(str(action["action"]))
    return found


def _read_sync(data: bytes, mime: str, anchors: TrustAnchors) -> C2PAResult:
    try:
        reader: Any = c2pa.Reader.try_create(  # pyright: ignore[reportUnknownMemberType]
            mime, io.BytesIO(data), context=_context(anchors)
        )
    except c2pa.C2paError as exc:  # pyright: ignore[reportUnknownMemberType]
        # try_create returns None when there is no C2PA data at all, so an error here means
        # C2PA data was found but could not be read. That is evidence too: never "none".
        return C2PAResult(
            C2PAState.PRESENT_UNTRUSTED, anchors.id, error=f"manifest unreadable: {exc}"
        )
    if reader is None:
        return C2PAResult(C2PAState.NONE, anchors.id)

    with reader:
        store = cast(dict[str, Any], json.loads(reader.json()))
        validation_state = cast(str | None, reader.get_validation_state())
        results = cast(dict[str, Any], reader.get_validation_results() or {})

    active_label = store.get("active_manifest")
    manifests = cast(dict[str, Any], store.get("manifests") or {})
    manifest = cast(dict[str, Any], manifests.get(active_label, {})) if active_label else {}
    signature = cast(dict[str, Any], manifest.get("signature_info") or {})
    active_results = cast(dict[str, Any], results.get("activeManifest") or {})
    failures = [
        str(item.get("code"))
        for item in cast(list[dict[str, Any]], active_results.get("failure") or [])
    ]
    state = (
        C2PAState.VALID_TRUSTED
        if validation_state == "Trusted" and not failures
        else C2PAState.PRESENT_UNTRUSTED
    )
    return C2PAResult(
        state=state,
        trust_list=anchors.id,
        validation_state=validation_state,
        failures=failures,
        signer_issuer=signature.get("issuer"),
        signer_common_name=signature.get("common_name"),
        signed_at=_parse_time(signature.get("time")),
        claim_generator=manifest.get("claim_generator")
        or ", ".join(
            str(info.get("name"))
            for info in cast(list[dict[str, Any]], manifest.get("claim_generator_info") or [])
        )
        or None,
        title=manifest.get("title"),
        actions=_actions(manifest),
        manifest_store=store,
    )


async def read_c2pa(data: bytes, mime: str, anchors: TrustAnchors | None = None) -> C2PAResult:
    """Read and validate the C2PA manifest store embedded in `data` (native code, off-loop)."""
    return await asyncio.to_thread(_read_sync, data, mime, anchors or official_trust_anchors())
