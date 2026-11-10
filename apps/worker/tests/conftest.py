"""Worker test fixtures. Model tests use the real SSCD weights and never download them.

Tests must run without network, so weights are fetched beforehand
(`python -m origin_worker.embedding download`). Without them, model tests are skipped
locally; CI sets ORIGIN_REQUIRE_MODEL=1 after its download step, so they cannot be skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from origin_worker.embedding import SSCDEmbedder, verify_weights, weights_path

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def models_dir() -> Path:
    return Path(os.environ.get("ORIGIN_MODELS_DIR", REPO / "models"))


@pytest.fixture(scope="session")
def embedder(models_dir: Path) -> SSCDEmbedder:
    path = weights_path(models_dir)
    if not path.exists():
        if os.environ.get("ORIGIN_REQUIRE_MODEL") == "1":
            pytest.fail(f"SSCD weights missing at {path}")
        pytest.skip("SSCD weights not downloaded (python -m origin_worker.embedding download)")
    verify_weights(path)
    return SSCDEmbedder(path)
