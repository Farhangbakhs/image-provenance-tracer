"""SSCD copy-detection embeddings (Meta, "A Self-Supervised Descriptor for Image Copy
Detection", CVPR 2022): 512-dimension, L2-normalised vectors whose cosine similarity stays
high under crops, overlays and other edits that defeat perceptual hashes.

The weights are MIT-licensed (confirmed by the maintainers in
facebookresearch/sscd-copy-detection#12). They are never committed: `ensure_weights`
downloads them once into the models directory and verifies a pinned SHA-256, so the model
that produced every stored embedding is known exactly.

    python -m origin_worker.embedding download     # fetch and verify the weights
"""

from __future__ import annotations

import argparse
import asyncio
import threading
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import numpy as np
import torch
from PIL import Image

from origin_core.hashing import sha256_hex
from origin_core.settings import get_settings


@dataclass(frozen=True)
class ModelSpec:
    name: str
    url: str
    sha256: str
    dim: int

    @property
    def id(self) -> str:
        """Recorded with every embedding: model name and weight hash."""
        return f"{self.name}@{self.sha256[:7]}"

    @property
    def filename(self) -> str:
        return f"{self.name}.torchscript.pt"


SSCD_DISC_MIXUP = ModelSpec(
    name="sscd_disc_mixup",
    url="https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt",
    sha256="9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56",
    dim=512,
)

#: Preprocessing from the SSCD README: shorter edge to 288 px, ImageNet normalisation.
SHORT_EDGE = 288
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class WeightsError(RuntimeError):
    pass


def weights_path(models_dir: Path, spec: ModelSpec = SSCD_DISC_MIXUP) -> Path:
    return models_dir / spec.filename


def verify_weights(path: Path, spec: ModelSpec = SSCD_DISC_MIXUP) -> None:
    actual = sha256_hex(path.read_bytes())
    if actual != spec.sha256:
        raise WeightsError(f"{path} has SHA-256 {actual}; expected {spec.sha256}")


def _ensure_weights_sync(models_dir: Path, spec: ModelSpec) -> Path:
    path = weights_path(models_dir, spec)
    if path.exists():
        verify_weights(path, spec)
        return path
    models_dir.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    timeout = httpx.Timeout(30, read=300)
    with (
        httpx.Client(timeout=timeout, follow_redirects=True) as http,
        http.stream("GET", spec.url) as response,
    ):
        response.raise_for_status()
        with partial.open("wb") as out:
            for chunk in response.iter_bytes(1 << 20):
                out.write(chunk)
    try:
        verify_weights(partial, spec)
    except WeightsError:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(path)
    return path


async def ensure_weights(models_dir: Path, spec: ModelSpec = SSCD_DISC_MIXUP) -> Path:
    """Return the verified weights file, downloading it first if it is missing.

    Runs in a thread: hashing 99 MB and streaming it to disk would block the event loop.
    """
    return await asyncio.to_thread(_ensure_weights_sync, models_dir, spec)


def preprocess(image: Image.Image) -> torch.Tensor:
    """RGB image -> normalised 1x3xHxW tensor with the shorter edge at SHORT_EDGE px."""
    rgb = image.convert("RGB")
    scale = SHORT_EDGE / min(rgb.size)
    size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
    resized = rgb.resize(size, Image.Resampling.BILINEAR)
    array = (np.asarray(resized, dtype=np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
    return torch.from_numpy(array.transpose(2, 0, 1).copy()).unsqueeze(0)


class SSCDEmbedder:
    """Loads the TorchScript model once; embedding runs off the event loop, one at a time."""

    def __init__(self, weights: Path, spec: ModelSpec = SSCD_DISC_MIXUP) -> None:
        with warnings.catch_warnings():
            # SSCD is published only as TorchScript; torch warns that the loader is deprecated.
            warnings.simplefilter("ignore", FutureWarning)
            loaded: Any = torch.jit.load(str(weights), map_location="cpu")  # pyright: ignore[reportUnknownMemberType, reportPrivateImportUsage, reportUnknownVariableType]
            # A TorchScript module is untyped; it maps a 1x3xHxW batch to 1x512 descriptors.
            self._model = cast(Callable[[torch.Tensor], torch.Tensor], loaded.eval())
        self.spec = spec
        self._lock = threading.Lock()

    def embed_sync(self, image: Image.Image) -> list[float]:
        batch = preprocess(image)
        with self._lock, torch.inference_mode():
            output = self._model(batch)
        vector = torch.nn.functional.normalize(output, dim=1)[0]
        if vector.shape[0] != self.spec.dim:
            raise WeightsError(
                f"model returned {vector.shape[0]} dimensions, expected {self.spec.dim}"
            )
        values = cast(list[float], vector.tolist())
        return [float(x) for x in values]

    async def embed(self, image: Image.Image) -> list[float]:
        return await asyncio.to_thread(self.embed_sync, image)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two L2-normalised vectors."""
    return float(np.dot(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="origin_worker.embedding")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("download", help="download and verify the SSCD weights")
    parser.parse_args(argv)
    path = asyncio.run(ensure_weights(get_settings().models_dir))
    print(f"{SSCD_DISC_MIXUP.id} ready at {path}")


if __name__ == "__main__":
    main()
