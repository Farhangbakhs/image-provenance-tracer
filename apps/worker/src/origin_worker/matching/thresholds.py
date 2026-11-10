"""Loading the versioned match thresholds."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

THRESHOLDS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class NearDuplicate:
    phash_max: int
    pdq_max: int
    pdq_min_quality: int


@dataclass(frozen=True)
class Derivative:
    sscd_min: float
    min_inliers: int
    orb_features: int
    lowe_ratio: float
    ransac_reproj_px: float
    max_edge: int


@dataclass(frozen=True)
class Transform:
    crop_area_max: float
    resize_tolerance: float
    overlay_min: float


@dataclass(frozen=True)
class Thresholds:
    version: str
    near_duplicate: NearDuplicate
    derivative: Derivative
    transform: Transform


@lru_cache(maxsize=4)
def load_thresholds(version: str = "v1") -> Thresholds:
    data = tomllib.loads((THRESHOLDS_DIR / f"thresholds.{version}.toml").read_text("utf-8"))
    return Thresholds(
        version=str(data["version"]),
        near_duplicate=NearDuplicate(**data["near_duplicate"]),
        derivative=Derivative(**data["derivative"]),
        transform=Transform(**data["transform"]),
    )
