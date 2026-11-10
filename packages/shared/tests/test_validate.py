"""Upload validation: magic bytes decide, limits hold before decoding, damage is caught."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from origin_core.ingest.validate import (
    DISPLAY_MAX_EDGE,
    ImageFormat,
    RejectReason,
    UploadRejected,
    sniff_format,
    validate_upload,
)

from .images import encode, exif_with_orientation, jpeg, scene

LIMITS = {"max_bytes": 5_000_000, "max_pixels": 2_000_000}


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("JPEG", ImageFormat.JPEG),
        ("PNG", ImageFormat.PNG),
        ("WEBP", ImageFormat.WEBP),
        ("GIF", ImageFormat.GIF),
    ],
)
def test_each_supported_format_is_recognised(fmt: str, expected: ImageFormat) -> None:
    data = encode(scene(64, 48), fmt)
    assert sniff_format(data) is expected
    result = validate_upload(data, **LIMITS)
    assert (result.format, result.width, result.height) == (expected, 64, 48)


def test_format_comes_from_bytes_not_names() -> None:
    # A PNG is a PNG whatever it claims to be; there is no name or declared type to consult.
    result = validate_upload(encode(scene(), "PNG"), **LIMITS)
    assert result.mime == "image/png"


@pytest.mark.parametrize(
    "data",
    [
        b"%PDF-1.7 not an image",
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        b"\x00" * 64,
        b"BM" + b"\x00" * 60,
    ],
)
def test_unsupported_content_is_refused(data: bytes) -> None:
    with pytest.raises(UploadRejected) as exc:
        validate_upload(data, **LIMITS)
    assert exc.value.reason is RejectReason.UNSUPPORTED_FORMAT


def test_empty_and_oversized_files_are_refused() -> None:
    with pytest.raises(UploadRejected) as empty:
        validate_upload(b"", **LIMITS)
    assert empty.value.reason is RejectReason.EMPTY
    with pytest.raises(UploadRejected) as big:
        validate_upload(jpeg(), max_bytes=100, max_pixels=LIMITS["max_pixels"])
    assert big.value.reason is RejectReason.TOO_LARGE


def _png_header_only(width: int, height: int) -> bytes:
    """A PNG whose header declares huge dimensions; decoding it would allocate gigabytes."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 16)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (2_000, 1_001),  # just over our limit: refused by ORIGIN's own header check
        (60_000, 60_000),  # far over: Pillow refuses it inside Image.open, still a clean 4xx
    ],
)
def test_pixel_bomb_is_refused_before_decoding(width: int, height: int) -> None:
    with pytest.raises(UploadRejected) as exc:
        validate_upload(_png_header_only(width, height), **LIMITS)
    assert exc.value.reason is RejectReason.TOO_MANY_PIXELS


def test_truncated_image_is_refused() -> None:
    data = jpeg(scene(400, 300))
    with pytest.raises(UploadRejected) as exc:
        validate_upload(data[: len(data) // 2], **LIMITS)
    assert exc.value.reason is RejectReason.CORRUPT


def test_original_bytes_are_kept_untouched() -> None:
    data = jpeg(exif=exif_with_orientation(6))
    assert validate_upload(data, **LIMITS).data == data


def test_display_copy_is_oriented_stripped_and_capped() -> None:
    # Orientation 6 means "rotate 90 degrees clockwise to display".
    data = jpeg(scene(3000, 600), exif=exif_with_orientation(6))
    result = validate_upload(data, max_bytes=LIMITS["max_bytes"], max_pixels=5_000_000)
    assert (result.width, result.height) == (3000, 600)  # as stored
    with Image.open(io.BytesIO(result.display)) as display:
        assert display.size == (result.display_width, result.display_height)
        assert max(display.size) == DISPLAY_MAX_EDGE
        assert display.height > display.width  # rotated upright
        assert 0x0112 not in display.getexif()  # metadata stripped


def test_transparent_png_display_keeps_png() -> None:
    rgba = Image.new("RGBA", (40, 30), (255, 0, 0, 0))
    result = validate_upload(encode(rgba, "PNG"), **LIMITS)
    assert result.display_mime == "image/png"
