"""Classify a fetched candidate against the query image.

    exact           identical bytes (SHA-256)
    near_duplicate  the same picture, resized or recompressed, possibly mirrored or rotated
                    (pHash or PDQ within threshold in any of the eight orientations)
    derivative      an edited copy: SSCD similarity above threshold AND confirmed by a
                    homography with enough inliers, which also says what was edited
    unrelated       none of the above; never becomes a sighting

Every result carries all its scores and the thresholds version, so a classification can be
audited and re-run after recalibration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from origin_core.enums import MatchClass
from origin_core.ingest.hashes import Fingerprints, Orientation, best_orientation, hamming
from origin_worker.embedding import cosine
from origin_worker.matching.geometry import Geometry, confirm
from origin_worker.matching.thresholds import Thresholds


@dataclass(frozen=True)
class Side:
    """Everything matching needs about one image."""

    fingerprints: Fingerprints
    embedding: list[float]
    image: Image.Image


@dataclass(frozen=True)
class MatchResult:
    match_class: MatchClass | None  # None means unrelated
    thresholds_version: str
    phash_distance: int
    pdq_distance: int
    orientation: Orientation
    sscd_cosine: float
    geometry: Geometry | None = None
    edits: list[str] = field(default_factory=list[str])
    reason: str = ""

    @property
    def related(self) -> bool:
        return self.match_class is not None

    def transform(self) -> dict[str, Any] | None:
        """The stored description of how the candidate differs from the query."""
        if self.geometry is None and self.orientation is Orientation.ORIGINAL:
            return None
        out: dict[str, Any] = {"orientation": self.orientation.value, "edits": self.edits}
        if self.geometry is not None:
            g = self.geometry
            out |= {
                "crop_box": list(g.crop_box),
                "mirrored": g.mirrored,
                "scale": round(g.scale, 4),
                "overlay_fraction": round(g.overlay_fraction, 4),
                "inliers": g.inliers,
            }
        return out


def classify(query: Side, candidate: Side, thresholds: Thresholds) -> MatchResult:
    q, c = query.fingerprints, candidate.fingerprints
    phash_distance = hamming(q.phash, c.phash)
    orientation, pdq_distance = best_orientation(q.pdq_dihedral, c.pdq)
    similarity = cosine(query.embedding, candidate.embedding)

    def result(
        match_class: MatchClass | None,
        reason: str,
        *,
        edits: list[str] | None = None,
        geometry: Geometry | None = None,
    ) -> MatchResult:
        return MatchResult(
            match_class=match_class,
            thresholds_version=thresholds.version,
            phash_distance=phash_distance,
            pdq_distance=pdq_distance,
            orientation=orientation,
            sscd_cosine=similarity,
            geometry=geometry,
            edits=edits or [],
            reason=reason,
        )

    if q.sha256 == c.sha256:
        return result(MatchClass.EXACT, "identical bytes")

    nd = thresholds.near_duplicate
    pdq_trusted = min(q.pdq_quality, c.pdq_quality) >= nd.pdq_min_quality
    if (orientation is Orientation.ORIGINAL and phash_distance <= nd.phash_max) or (
        pdq_trusted and pdq_distance <= nd.pdq_max
    ):
        edits = (
            []
            if orientation is Orientation.ORIGINAL
            else ["mirror" if "flip" in orientation.value else "rotate"]
        )
        reason = (
            f"pHash {phash_distance} <= {nd.phash_max}"
            if orientation is Orientation.ORIGINAL and phash_distance <= nd.phash_max
            else f"PDQ {pdq_distance} <= {nd.pdq_max} ({orientation.value})"
        )
        return result(MatchClass.NEAR_DUPLICATE, reason, edits=edits)

    d = thresholds.derivative
    screen = d.sscd_screen if d.sscd_screen is not None else d.sscd_min
    if similarity < screen:
        return result(None, f"SSCD {similarity:.3f} < {screen}")
    geometry = confirm(query.image, candidate.image, d)
    if geometry is None:
        return result(
            None, f"SSCD {similarity:.3f} but no homography with >= {d.min_inliers} inliers"
        )
    if similarity >= d.sscd_min:
        reason = f"SSCD {similarity:.3f} >= {d.sscd_min}, {geometry.inliers} inliers"
    elif d.strong_inliers is not None and geometry.inliers >= d.strong_inliers:
        reason = (
            f"SSCD {similarity:.3f} below {d.sscd_min} but {geometry.inliers} inliers "
            f">= {d.strong_inliers} confirm the same scene"
        )
    else:
        return result(
            None,
            f"SSCD {similarity:.3f} < {d.sscd_min} and only {geometry.inliers} inliers",
        )
    return result(
        MatchClass.DERIVATIVE,
        reason,
        edits=geometry.edits(thresholds.transform),
        geometry=geometry,
    )
