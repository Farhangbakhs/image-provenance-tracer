"""Geometric confirmation of a derivative with ORB keypoints and a RANSAC homography.

An SSCD similarity says two images look alike; it does not say how one was made from the
other. Here keypoints of the candidate are matched to the query and fitted to a single
homography. Enough consistent matches (inliers) confirm the candidate shows the same scene,
and the homography itself tells us what was done: which part of the query frame the candidate
covers (a crop), whether it is mirrored, how it was scaled, and how much of the overlapping
region differs strongly (a caption or overlay).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np
from PIL import Image

from origin_worker.matching.thresholds import Derivative, Transform

# OpenCV's type stubs are incomplete; the calls below are typed at this boundary instead.
cv: Any = cv2


@dataclass(frozen=True)
class Geometry:
    inliers: int
    mirrored: bool
    #: The part of the query frame the candidate covers: (x0, y0, x1, y1), each 0..1.
    crop_box: tuple[float, float, float, float]
    #: Candidate size relative to the same region of the query (1.0: same scale).
    scale: float
    #: Share of the overlapping region that differs strongly from the query.
    overlay_fraction: float

    @property
    def covered_area(self) -> float:
        x0, y0, x1, y1 = self.crop_box
        return max(0.0, x1 - x0) * max(0.0, y1 - y0)

    def edits(self, limits: Transform) -> list[str]:
        """The transformations this geometry implies, in the variant-edge vocabulary."""
        found: list[str] = []
        if self.covered_area < limits.crop_area_max:
            found.append("crop")
        if self.mirrored:
            found.append("mirror")
        if abs(self.scale - 1.0) > limits.resize_tolerance:
            found.append("resize")
        if self.overlay_fraction > limits.overlay_min:
            found.append("overlay")
        return found


def _grey(image: Image.Image, max_edge: int) -> tuple[np.ndarray, float]:
    """Greyscale array at most max_edge on the long side, and the factor applied."""
    factor = min(1.0, max_edge / max(image.size))
    if factor < 1.0:
        size = (max(1, round(image.width * factor)), max(1, round(image.height * factor)))
        image = image.resize(size, Image.Resampling.BILINEAR)
    return np.asarray(image.convert("L"), dtype=np.uint8), factor


def _fit(
    query: np.ndarray, candidate: np.ndarray, params: Derivative
) -> tuple[int, np.ndarray | None]:
    orb: Any = cv.ORB_create(nfeatures=params.orb_features)
    kq: Any
    dq: Any
    kc: Any
    dc: Any
    kq, dq = orb.detectAndCompute(query, None)
    kc, dc = orb.detectAndCompute(candidate, None)
    if dq is None or dc is None or len(kq) < 4 or len(kc) < 4:
        return 0, None
    matcher: Any = cv.BFMatcher(cv.NORM_HAMMING)
    pairs = cast(list[list[Any]], matcher.knnMatch(dc, dq, k=2))
    good = [
        p[0] for p in pairs if len(p) == 2 and p[0].distance < params.lowe_ratio * p[1].distance
    ]
    if len(good) < 4:
        return len(good), None
    src = np.array([kc[m.queryIdx].pt for m in good], dtype=np.float32).reshape(-1, 1, 2)
    dst = np.array([kq[m.trainIdx].pt for m in good], dtype=np.float32).reshape(-1, 1, 2)
    homography: Any
    mask: Any
    homography, mask = cv.findHomography(src, dst, cv.RANSAC, params.ransac_reproj_px)
    if homography is None or mask is None:
        return 0, None
    return int(np.asarray(mask).sum()), np.asarray(homography, dtype=np.float64)


def _overlay_fraction(query: np.ndarray, candidate: np.ndarray, homography: np.ndarray) -> float:
    """Warp the candidate onto the query frame and measure strong differences where they overlap."""
    height, width = query.shape
    warped: np.ndarray = cv.warpPerspective(candidate, homography, (width, height))
    coverage: np.ndarray = cv.warpPerspective(
        np.full(candidate.shape, 255, np.uint8), homography, (width, height)
    )
    inside = coverage > 0
    if not inside.any():
        return 0.0
    blurred_q = cv.GaussianBlur(query, (5, 5), 0)
    blurred_w = cv.GaussianBlur(warped, (5, 5), 0)
    diff = np.abs(blurred_q.astype(np.int16) - blurred_w.astype(np.int16))
    return float((diff[inside] > 60).mean())


def confirm(query: Image.Image, candidate: Image.Image, params: Derivative) -> Geometry | None:
    """Fit the candidate to the query, trying it as is and mirrored. None if it does not fit."""
    q, _ = _grey(query, params.max_edge)
    c, c_factor = _grey(candidate, params.max_edge)
    best: tuple[int, np.ndarray | None, bool, np.ndarray] = (0, None, False, c)
    for mirrored in (False, True):
        image = np.ascontiguousarray(c[:, ::-1]) if mirrored else c
        inliers, homography = _fit(q, image, params)
        if inliers > best[0]:
            best = (inliers, homography, mirrored, image)
    inliers, homography, mirrored, fitted = best
    if homography is None or inliers < params.min_inliers:
        return None

    h, w = fitted.shape
    corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32).reshape(-1, 1, 2)
    projected = cast(np.ndarray, cv.perspectiveTransform(corners, homography)).reshape(-1, 2)
    qh, qw = q.shape
    x0, y0 = projected.min(axis=0)
    x1, y1 = projected.max(axis=0)
    box = (
        float(np.clip(x0 / qw, 0, 1)),
        float(np.clip(y0 / qh, 0, 1)),
        float(np.clip(x1 / qw, 0, 1)),
        float(np.clip(y1 / qh, 0, 1)),
    )
    # Area scale of the homography's linear part, corrected for the working resolutions.
    q_factor = min(1.0, params.max_edge / max(query.size))
    linear = homography[:2, :2] / homography[2, 2]
    area_scale = abs(float(np.linalg.det(linear)))
    scale = (1 / np.sqrt(area_scale)) * (q_factor / c_factor) if area_scale > 0 else 0.0
    return Geometry(
        inliers=inliers,
        mirrored=mirrored,
        crop_box=box,
        scale=float(scale),
        overlay_fraction=_overlay_fraction(q, fitted, homography),
    )
