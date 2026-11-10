"""SSCD embeddings: robust to the edits hashes miss, and still able to tell pictures apart.

The similarity bounds here only check that the model is wired correctly. The thresholds that
classify real matches are calibrated on the eval set and live in the versioned matching config.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageOps

from origin_worker.embedding import (
    IMAGENET_MEAN,
    SHORT_EDGE,
    SSCD_DISC_MIXUP,
    SSCDEmbedder,
    WeightsError,
    cosine,
    preprocess,
    verify_weights,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"


def _photo(name: str) -> Image.Image:
    with Image.open(io.BytesIO((FIXTURES / name).read_bytes())) as image:
        return image.convert("RGB")


def test_preprocess_scales_short_edge_and_normalises() -> None:
    tensor = preprocess(Image.new("RGB", (800, 400), (124, 116, 104)))
    assert tuple(tensor.shape) == (1, 3, SHORT_EDGE, SHORT_EDGE * 2)
    # A pixel equal to the ImageNet mean normalises to roughly zero.
    assert np.allclose(tensor.mean(dim=(2, 3)).numpy()[0], 0.0, atol=0.02)
    assert IMAGENET_MEAN.shape == (3,)


def test_corrupted_weights_are_refused(tmp_path: Path) -> None:
    fake = tmp_path / SSCD_DISC_MIXUP.filename
    fake.write_bytes(b"not the model")
    with pytest.raises(WeightsError, match="expected"):
        verify_weights(fake)


def test_embedding_is_unit_length_and_deterministic(embedder: SSCDEmbedder) -> None:
    photo = _photo("no-manifest.jpg")
    first = embedder.embed_sync(photo)
    assert len(first) == 512
    assert sum(x * x for x in first) == pytest.approx(1.0, abs=1e-4)
    assert cosine(first, embedder.embed_sync(photo)) == pytest.approx(1.0, abs=1e-5)


def test_edited_copies_stay_close_and_other_photos_do_not(embedder: SSCDEmbedder) -> None:
    photo = _photo("no-manifest.jpg")
    other = _photo("signed-test-cert.jpg")
    w, h = photo.size
    reference = embedder.embed_sync(photo)

    cropped = photo.crop((int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85)))
    captioned = photo.copy()
    ImageDraw.Draw(captioned).rectangle((0, int(h * 0.82), w, h), fill=(0, 0, 0))
    resized = photo.resize((w // 3, h // 3))

    unrelated = cosine(reference, embedder.embed_sync(other))
    for edited in (cropped, captioned, resized, ImageOps.mirror(photo)):
        similarity = cosine(reference, embedder.embed_sync(edited))
        assert similarity > 0.75
        assert similarity > unrelated + 0.2
