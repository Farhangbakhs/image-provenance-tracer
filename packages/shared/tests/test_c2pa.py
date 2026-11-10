"""Content Credentials: the three states, an invalid manifest never shown as merely untrusted,
and a pinned, hash-checked trust list."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import c2pa  # pyright: ignore[reportMissingTypeStubs]
import pytest

from origin_core.enums import C2PAState
from origin_core.ingest import c2pa as c2pa_module
from origin_core.ingest.c2pa import (
    TRUST_LIST_ID,
    TrustListError,
    official_trust_anchors,
    read_c2pa,
    with_extra_anchors,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _test_root_pem() -> str:
    chain = _fixture("test-es256-chain.pem").decode("ascii")
    blocks = [
        "-----BEGIN CERTIFICATE-----" + b for b in chain.split("-----BEGIN CERTIFICATE-----")[1:]
    ]
    return blocks[-1]


def _sign(image: bytes) -> bytes:
    """Sign an image with c2pa-python's published test credentials."""
    info = c2pa.C2paSignerInfo(  # pyright: ignore[reportUnknownMemberType]
        alg=b"es256",
        sign_cert=_fixture("test-es256-chain.pem"),
        private_key=_fixture("test-es256-private.key"),
        ta_url=None,  # None means "no timestamp authority"; an empty string breaks signing
    )
    signer = c2pa.Signer.from_info(info)  # pyright: ignore[reportUnknownMemberType]
    manifest = {
        "claim_generator_info": [{"name": "origin-tests", "version": "1"}],
        "title": "signed-for-tests.jpg",
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            # Required by the C2PA spec on a "created" action.
                            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture",
                        }
                    ]
                },
            }
        ],
    }
    out = io.BytesIO()
    with c2pa.Builder(manifest) as builder:  # pyright: ignore[reportUnknownMemberType]
        builder.sign(signer, "image/jpeg", io.BytesIO(image), out)  # pyright: ignore[reportUnknownMemberType]
    return out.getvalue()


async def test_image_without_manifest_is_none() -> None:
    result = await read_c2pa(_fixture("no-manifest.jpg"), "image/jpeg")
    assert result.state is C2PAState.NONE
    assert result.trust_list == TRUST_LIST_ID
    assert result.manifest_store is None


async def test_test_signed_image_is_present_but_untrusted() -> None:
    result = await read_c2pa(_fixture("signed-test-cert.jpg"), "image/jpeg")
    assert result.state is C2PAState.PRESENT_UNTRUSTED
    assert result.validation_state == "Valid"
    assert "signingCredential.untrusted" in result.failures
    assert result.signer_issuer == "C2PA Test Signing Cert"
    assert result.signed_at == datetime(2023, 9, 29, 17, 40, 14, tzinfo=UTC)
    assert result.manifest_store is not None


async def test_signer_chaining_to_a_trust_anchor_is_valid_trusted() -> None:
    signed = _sign(_fixture("no-manifest.jpg"))
    anchors = with_extra_anchors(official_trust_anchors(), _test_root_pem(), "test-root")

    trusted = await read_c2pa(signed, "image/jpeg", anchors)
    assert trusted.state is C2PAState.VALID_TRUSTED
    assert trusted.validation_state == "Trusted"
    assert trusted.failures == []
    assert trusted.actions == ["c2pa.created"]
    assert trusted.title == "signed-for-tests.jpg"
    assert trusted.trust_list == f"{TRUST_LIST_ID}+test-root"

    # The same file against the official list alone: valid signature, untrusted signer.
    official = await read_c2pa(signed, "image/jpeg")
    assert official.state is C2PAState.PRESENT_UNTRUSTED
    assert official.validation_state == "Valid"


async def test_tampered_image_reports_invalid_not_just_untrusted() -> None:
    signed = bytearray(_sign(_fixture("no-manifest.jpg")))
    signed[-200] ^= 0xFF  # change pixel data after signing
    anchors = with_extra_anchors(official_trust_anchors(), _test_root_pem(), "test-root")

    result = await read_c2pa(bytes(signed), "image/jpeg", anchors)
    assert result.state is C2PAState.PRESENT_UNTRUSTED
    assert result.validation_state == "Invalid"
    assert "assertion.dataHash.mismatch" in result.failures


def test_official_trust_list_is_pinned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    anchors = official_trust_anchors()
    assert anchors.pem.count("BEGIN CERTIFICATE") == 33

    altered = tmp_path / "C2PA-TRUST-LIST.pem"
    altered.write_text(anchors.pem + "\n", encoding="ascii")
    monkeypatch.setattr(c2pa_module, "TRUST_LIST_FILE", altered)
    official_trust_anchors.cache_clear()
    try:
        with pytest.raises(TrustListError, match="expected"):
            official_trust_anchors()
    finally:
        official_trust_anchors.cache_clear()
