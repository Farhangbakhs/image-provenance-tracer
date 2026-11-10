"""Deterministic test images, generated in code so no binary needs to be committed."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw


def scene(width: int = 320, height: int = 240, *, seed: int = 0) -> Image.Image:
    """A structured image (gradient, shapes, text-like bars) with real detail to hash."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                (x * 255) // width,
                (y * 255) // height,
                ((x + y + seed * 37) * 3) % 256,
            )
    draw = ImageDraw.Draw(image)
    draw.ellipse((width * 0.1, height * 0.15, width * 0.45, height * 0.7), fill=(20, 30, 200))
    draw.rectangle((width * 0.55, height * 0.2, width * 0.9, height * 0.55), fill=(230, 200, 20))
    draw.polygon(
        [(width * 0.2, height * 0.9), (width * 0.5, height * 0.6), (width * 0.8, height * 0.95)],
        fill=(200, 30, 40 + seed * 50 % 200),
    )
    for i in range(6):
        y = int(height * (0.08 + 0.025 * i))
        draw.rectangle(
            (width * 0.55, y, width * (0.6 + 0.05 * ((i + seed) % 6)), y + 3), fill=(0, 0, 0)
        )
    return image


def encode(image: Image.Image, fmt: str = "JPEG", **params: object) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **params)
    return out.getvalue()


def jpeg(
    image: Image.Image | None = None, *, quality: int = 92, exif: bytes | None = None
) -> bytes:
    image = image or scene()
    if exif is None:
        return encode(image, "JPEG", quality=quality)
    return encode(image, "JPEG", quality=quality, exif=exif)


def exif_with_orientation(orientation: int) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = orientation
    return exif.tobytes()
