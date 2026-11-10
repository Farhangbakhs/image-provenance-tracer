"""Matching on a real photograph and edited copies of it, through the full classifier."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageOps

from origin_core.enums import MatchClass
from origin_core.ingest.hashes import fingerprint
from origin_core.ingest.validate import decode_rgb
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.classify import MatchResult, Side, classify
from origin_worker.matching.geometry import confirm
from origin_worker.matching.thresholds import load_thresholds

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"
T = load_thresholds("v1")


def _jpeg(image: Image.Image, quality: int = 90) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def _side(data: bytes, embedder: SSCDEmbedder) -> Side:
    image = decode_rgb(data)
    return Side(fingerprint(data, image), embedder.embed_sync(image), image)


@pytest.fixture(scope="module")
def photo() -> Image.Image:
    return decode_rgb((FIXTURES / "no-manifest.jpg").read_bytes())


@pytest.fixture(scope="module")
def query(photo: Image.Image, embedder: SSCDEmbedder) -> Side:
    return _side((FIXTURES / "no-manifest.jpg").read_bytes(), embedder)


def _match(query: Side, edited: Image.Image, embedder: SSCDEmbedder) -> MatchResult:
    return classify(query, _side(_jpeg(edited), embedder), T)


def test_thresholds_are_versioned() -> None:
    assert T.version == "match.v1"
    assert T.derivative.sscd_min == 0.75


def test_identical_bytes_are_exact(query: Side, embedder: SSCDEmbedder) -> None:
    result = classify(query, _side((FIXTURES / "no-manifest.jpg").read_bytes(), embedder), T)
    assert result.match_class is MatchClass.EXACT
    assert result.transform() is None


def test_recompressed_copy_is_near_duplicate(
    query: Side, photo: Image.Image, embedder: SSCDEmbedder
) -> None:
    result = _match(query, photo.resize((photo.width // 2, photo.height // 2)), embedder)
    assert result.match_class is MatchClass.NEAR_DUPLICATE
    assert result.edits == []


def test_mirrored_copy_is_near_duplicate_with_mirror(
    query: Side, photo: Image.Image, embedder: SSCDEmbedder
) -> None:
    result = _match(query, ImageOps.mirror(photo), embedder)
    assert result.match_class is MatchClass.NEAR_DUPLICATE
    assert result.edits == ["mirror"]


def test_crop_is_a_derivative_with_its_box(
    query: Side, photo: Image.Image, embedder: SSCDEmbedder
) -> None:
    w, h = photo.size
    result = _match(
        query, photo.crop((int(w * 0.2), int(h * 0.1), int(w * 0.9), int(h * 0.8))), embedder
    )
    assert result.match_class is MatchClass.DERIVATIVE
    assert "crop" in result.edits
    assert result.geometry is not None
    x0, y0, x1, y1 = result.geometry.crop_box
    assert (x0, y0, x1, y1) == pytest.approx((0.2, 0.1, 0.9, 0.8), abs=0.03)
    assert result.geometry.scale == pytest.approx(1.0, abs=0.05)


def test_caption_overlay_is_detected(
    query: Side, photo: Image.Image, embedder: SSCDEmbedder
) -> None:
    edited = photo.copy()
    w, h = edited.size
    ImageDraw.Draw(edited).rectangle((0, int(h * 0.72), w, h), fill=(0, 0, 0))
    result = _match(query, edited, embedder)
    assert result.match_class is MatchClass.DERIVATIVE
    assert "overlay" in result.edits


def test_cropped_and_mirrored_derivative(
    query: Side, photo: Image.Image, embedder: SSCDEmbedder
) -> None:
    w, h = photo.size
    edited = ImageOps.mirror(photo.crop((int(w * 0.1), int(h * 0.1), int(w * 0.85), int(h * 0.9))))
    result = _match(query, edited, embedder)
    assert result.match_class is MatchClass.DERIVATIVE
    assert {"crop", "mirror"} <= set(result.edits)


def test_unrelated_photo_is_rejected(query: Side, embedder: SSCDEmbedder) -> None:
    result = classify(query, _side((FIXTURES / "signed-test-cert.jpg").read_bytes(), embedder), T)
    assert result.match_class is None
    assert not result.related
    assert "SSCD" in result.reason


def test_geometry_rejects_noise(photo: Image.Image) -> None:
    noise = Image.effect_noise((640, 480), 80).convert("RGB")
    assert confirm(photo, noise, T.derivative) is None


def test_v2_accepts_a_heavy_crop_with_caption_that_v1_missed(
    query: Side, photo: Image.Image, embedder: SSCDEmbedder
) -> None:
    w, h = photo.size
    edited = photo.crop((int(w * 0.1), int(h * 0.05), int(w * 0.9), int(h * 0.85)))
    ImageDraw.Draw(edited).rectangle(
        (0, int(edited.height * 0.8), edited.width, edited.height), fill=(0, 0, 0)
    )
    candidate = _side(_jpeg(edited), embedder)
    v1 = classify(query, candidate, load_thresholds("v1"))
    v2 = classify(query, candidate, load_thresholds("v2"))
    assert v1.match_class is None  # SSCD alone is below 0.75
    assert v2.match_class is MatchClass.DERIVATIVE
    assert "inliers" in v2.reason and v2.thresholds_version == "match.v2"
    assert {"crop", "overlay"} <= set(v2.edits)


def test_v2_still_rejects_unrelated_photos(query: Side, embedder: SSCDEmbedder) -> None:
    other = _side((FIXTURES / "signed-test-cert.jpg").read_bytes(), embedder)
    assert classify(query, other, load_thresholds("v2")).match_class is None
