"""Fingerprints: stable, robust to resizing and recompression, discriminating, orientation-aware."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from PIL import Image, ImageOps

from origin_core.hashing import sha256_hex
from origin_core.ingest.hashes import (
    PDQ_BITS,
    Fingerprints,
    Orientation,
    best_orientation,
    fingerprint,
    hamming,
)
from origin_core.ingest.validate import decode_rgb

from .images import jpeg, scene

# Generous bounds for "same picture" used only to check robustness here; the calibrated
# thresholds that classify real matches live in the versioned matching config (Phase 2).
SAME_PHASH = 10
SAME_PDQ = 40
DIFFERENT_PDQ = 80


def _fp(image: Image.Image, quality: int = 92) -> Fingerprints:
    data = jpeg(image, quality=quality)
    return fingerprint(data, decode_rgb(data))


def test_formats_and_exact_hash() -> None:
    data = jpeg()
    fp = fingerprint(data, decode_rgb(data))
    assert fp.sha256 == sha256_hex(data)
    assert len(fp.phash) == 16 and len(fp.dhash) == 16
    assert len(fp.pdq) == PDQ_BITS // 4
    assert set(fp.pdq_dihedral) == set(Orientation)
    assert fp.pdq_dihedral[Orientation.ORIGINAL] == fp.pdq
    assert 0 <= fp.pdq_quality <= 100


def test_fingerprints_are_deterministic() -> None:
    assert _fp(scene()) == _fp(scene())


def test_resized_and_recompressed_copy_stays_close() -> None:
    original = _fp(scene(640, 480))
    copy = _fp(scene(640, 480).resize((320, 240), Image.Resampling.BILINEAR), quality=60)
    assert copy.sha256 != original.sha256
    assert hamming(original.phash, copy.phash) <= SAME_PHASH
    assert hamming(original.pdq, copy.pdq) <= SAME_PDQ


def test_different_picture_is_far() -> None:
    a = _fp(scene(seed=0))
    b = _fp(ImageOps.invert(scene(seed=3)).rotate(17))
    assert hamming(a.pdq, b.pdq) >= DIFFERENT_PDQ


def _rotate_180(image: Image.Image) -> Image.Image:
    return image.rotate(180)


@pytest.mark.parametrize(
    ("transform", "expected"),
    [
        (ImageOps.mirror, Orientation.FLIP_HORIZONTAL),
        (ImageOps.flip, Orientation.FLIP_VERTICAL),
        (_rotate_180, Orientation.ROTATE_180),
    ],
)
def test_mirrored_or_rotated_copy_is_identified(
    transform: Callable[[Image.Image], Image.Image], expected: Orientation
) -> None:
    query = _fp(scene(400, 300))
    candidate = _fp(transform(scene(400, 300)))
    assert hamming(query.pdq, candidate.pdq) >= DIFFERENT_PDQ  # direct comparison misses it
    orientation, distance = best_orientation(query.pdq_dihedral, candidate.pdq)
    assert orientation is expected
    assert distance <= SAME_PDQ


def test_hamming_checks_lengths() -> None:
    assert hamming("ff", "0f") == 4
    with pytest.raises(ValueError, match="lengths differ"):
        hamming("ff", "fff")


def test_orientation_metadata_is_respected() -> None:
    # A JPEG stored sideways with an EXIF orientation flag fingerprints like the upright image.
    upright = scene(300, 200)
    exif = Image.Exif()
    exif[0x0112] = 6  # display rotated 90 degrees clockwise
    stored_sideways = upright.rotate(90, expand=True)
    out = io.BytesIO()
    stored_sideways.save(out, format="JPEG", quality=92, exif=exif.tobytes())
    sideways = fingerprint(out.getvalue(), decode_rgb(out.getvalue()))
    assert hamming(sideways.pdq, _fp(upright).pdq) <= SAME_PDQ
