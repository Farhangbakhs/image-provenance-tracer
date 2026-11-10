"""Upload validation: decide what a file is from its bytes, and refuse anything unsafe.

* The format comes from magic bytes; the filename and declared content type are ignored.
* Pixel count is read from the header and capped *before* decoding, so a decompression bomb
  is refused without allocating its pixels.
* The image is then fully decoded, which catches truncated and corrupt files.
* A display copy is re-encoded (orientation applied, metadata stripped, long edge capped). The
  console only ever shows that copy; the original bytes are kept untouched as evidence.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field
from enum import StrEnum

from PIL import Image, ImageOps, UnidentifiedImageError


class ImageFormat(StrEnum):
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    GIF = "gif"


MIME_TYPES: dict[ImageFormat, str] = {
    ImageFormat.JPEG: "image/jpeg",
    ImageFormat.PNG: "image/png",
    ImageFormat.WEBP: "image/webp",
    ImageFormat.GIF: "image/gif",
}

PIL_FORMATS: dict[ImageFormat, str] = {
    ImageFormat.JPEG: "JPEG",
    ImageFormat.PNG: "PNG",
    ImageFormat.WEBP: "WEBP",
    ImageFormat.GIF: "GIF",
}

DISPLAY_MAX_EDGE = 2048


class RejectReason(StrEnum):
    EMPTY = "empty"
    TOO_LARGE = "too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"
    TOO_MANY_PIXELS = "too_many_pixels"
    CORRUPT = "corrupt"


class UploadRejected(Exception):
    def __init__(self, reason: RejectReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes = field(repr=False)
    format: ImageFormat
    width: int
    height: int
    frames: int
    display: bytes = field(repr=False)
    display_mime: str
    display_width: int
    display_height: int

    @property
    def mime(self) -> str:
        return MIME_TYPES[self.format]


def sniff_format(data: bytes) -> ImageFormat | None:
    """Identify a supported image format from its leading bytes."""
    if data.startswith(b"\xff\xd8\xff"):
        return ImageFormat.JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ImageFormat.PNG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ImageFormat.WEBP
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ImageFormat.GIF
    return None


def _megabytes(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def validate_upload(data: bytes, *, max_bytes: int, max_pixels: int) -> ValidatedImage:
    if not data:
        raise UploadRejected(RejectReason.EMPTY, "The file is empty.")
    if len(data) > max_bytes:
        raise UploadRejected(
            RejectReason.TOO_LARGE,
            f"The file is {_megabytes(len(data))}; the limit is {_megabytes(max_bytes)}.",
        )
    fmt = sniff_format(data)
    if fmt is None:
        raise UploadRejected(
            RejectReason.UNSUPPORTED_FORMAT,
            "Unsupported file type. ORIGIN accepts JPEG, PNG, WebP and GIF images.",
        )

    try:
        with warnings.catch_warnings():
            # Pillow's own bomb check would warn or raise on its threshold; ours runs first.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[PIL_FORMATS[fmt]]) as header:
                width, height = header.size
                frames = int(getattr(header, "n_frames", 1))
    except Image.DecompressionBombError as exc:
        # Pillow refuses headers far beyond its own limit before ours can run.
        raise UploadRejected(
            RejectReason.TOO_MANY_PIXELS,
            f"The image declares far more pixels than the {max_pixels / 1e6:.0f} MP limit.",
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UploadRejected(RejectReason.CORRUPT, f"The image could not be read: {exc}") from exc

    if width <= 0 or height <= 0:
        raise UploadRejected(RejectReason.CORRUPT, "The image has no pixels.")
    if width * height > max_pixels:
        raise UploadRejected(
            RejectReason.TOO_MANY_PIXELS,
            f"The image is {width}x{height} ({width * height / 1e6:.1f} MP); "
            f"the limit is {max_pixels / 1e6:.0f} MP.",
        )

    try:
        decoded = decode_rgb(data, fmt)
    except (OSError, SyntaxError, ValueError) as exc:
        raise UploadRejected(RejectReason.CORRUPT, f"The image is damaged: {exc}") from exc

    display, display_mime, (display_width, display_height) = _display_copy(decoded, fmt)
    return ValidatedImage(
        data=data,
        format=fmt,
        width=width,
        height=height,
        frames=frames,
        display=display,
        display_mime=display_mime,
        display_width=display_width,
        display_height=display_height,
    )


def decode_rgb(data: bytes, fmt: ImageFormat | None = None) -> Image.Image:
    """Fully decode the first frame, apply EXIF orientation, and return an RGB image.

    Orientation is applied because copies found online almost always have it baked into the
    pixels, so matching must compare the image as people see it.
    """
    formats = [PIL_FORMATS[fmt]] if fmt else None
    with Image.open(io.BytesIO(data), formats=formats) as image:
        image.load()
        oriented = ImageOps.exif_transpose(image)
        if oriented.mode in ("RGBA", "LA") or (
            oriented.mode == "P" and "transparency" in oriented.info
        ):
            rgba = oriented.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            return background
        return oriented.convert("RGB")


def _display_copy(image: Image.Image, fmt: ImageFormat) -> tuple[bytes, str, tuple[int, int]]:
    copy = image.copy()
    copy.thumbnail((DISPLAY_MAX_EDGE, DISPLAY_MAX_EDGE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if fmt is ImageFormat.PNG:
        copy.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png", copy.size
    copy.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue(), "image/jpeg", copy.size
