"""Image fingerprints: exact (SHA-256) and perceptual (pHash, dHash, PDQ).

* SHA-256 is over the original bytes: equal hashes mean the identical file.
* pHash and dHash (64-bit, imagehash) and PDQ (256-bit, Meta) are over the decoded, oriented
  pixels. They survive resizing and recompression; a small Hamming distance means "the same
  picture". They do not survive crops or heavy overlays; SSCD embeddings handle those.
* PDQ is also computed for the image's eight rotations and mirrors ("dihedral"), so a
  mirrored or rotated copy is recognised with one comparison per orientation.

Thresholds that turn distances into match classes live in the versioned matching config,
not here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

import imagehash
import numpy as np
import pdqhash  # pyright: ignore[reportMissingTypeStubs]
from PIL import Image

from origin_core.hashing import sha256_hex

PDQ_BITS = 256


class Orientation(StrEnum):
    """The eight dihedral transforms, in the order pdqhash.compute_dihedral returns them."""

    ORIGINAL = "original"
    ROTATE_90 = "rotate_90"
    ROTATE_180 = "rotate_180"
    ROTATE_270 = "rotate_270"
    FLIP_VERTICAL = "flip_vertical"
    FLIP_HORIZONTAL = "flip_horizontal"
    ROTATE_90_FLIP_VERTICAL = "rotate_90_flip_vertical"
    ROTATE_90_FLIP_HORIZONTAL = "rotate_90_flip_horizontal"


DIHEDRAL_ORDER: tuple[Orientation, ...] = tuple(Orientation)


@dataclass(frozen=True)
class Fingerprints:
    sha256: str
    phash: str
    dhash: str
    pdq: str
    pdq_quality: int
    pdq_dihedral: dict[Orientation, str]


def _bits_to_hex(bits: np.ndarray) -> str:
    packed = np.packbits(bits.astype(np.uint8))
    return packed.tobytes().hex()


def _pdq(image: Image.Image) -> tuple[str, int, dict[Orientation, str]]:
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint8)
    # pdqhash ships no type information; pin down what it returns at this one boundary.
    compute = cast(Callable[[np.ndarray], tuple[np.ndarray, int]], pdqhash.compute)  # pyright: ignore[reportUnknownMemberType]
    compute_dihedral = cast(
        Callable[[np.ndarray], tuple[list[np.ndarray], int]],
        pdqhash.compute_dihedral,  # pyright: ignore[reportUnknownMemberType]
    )
    vector, quality = compute(pixels)
    vectors, _ = compute_dihedral(pixels)
    dihedral = {
        orientation: _bits_to_hex(v) for orientation, v in zip(DIHEDRAL_ORDER, vectors, strict=True)
    }
    return _bits_to_hex(vector), int(quality), dihedral


def fingerprint(data: bytes, image: Image.Image) -> Fingerprints:
    """Fingerprint an upload. `image` is the decoded, oriented RGB image of `data`."""
    pdq, quality, dihedral = _pdq(image)
    return Fingerprints(
        sha256=sha256_hex(data),
        phash=str(imagehash.phash(image)),
        dhash=str(imagehash.dhash(image)),
        pdq=pdq,
        pdq_quality=quality,
        pdq_dihedral=dihedral,
    )


def hamming(a: str, b: str) -> int:
    """Hamming distance between two equal-length hex-encoded hashes."""
    if len(a) != len(b):
        raise ValueError(f"hash lengths differ: {len(a)} vs {len(b)}")
    return (int(a, 16) ^ int(b, 16)).bit_count()


def best_orientation(
    query_dihedral: dict[Orientation, str], candidate_pdq: str
) -> tuple[Orientation, int]:
    """The orientation of the query that best matches the candidate, and its PDQ distance.

    If the best match is not ORIGINAL, the candidate is a rotated or mirrored copy.
    """
    best = min(query_dihedral.items(), key=lambda item: hamming(item[1], candidate_pdq))
    return best[0], hamming(best[1], candidate_pdq)
