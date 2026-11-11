"""Variants and how they derive from one another.

A *variant* is a set of sightings showing the same picture in the same form: identical bytes,
or the same pixels resized or recompressed (pHash or PDQ within threshold, unrotated). A mirror,
crop or overlay is an edit and therefore a different variant.

Derived-from edges between variants come from evidence, in this order:

1. containment: a variant that covers only part of another's frame is a crop of it;
2. resolution: of two variants covering the same frame, the smaller one came from the larger;
3. time: only when neither says which came first, the earlier-dated variant is the parent.

Each variant gets at most one parent: the *closest* container (the smallest frame that still
contains it), so the result is a forest, not a tangle. Every edge records why it exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PIL import Image

from origin_core.ingest.hashes import Fingerprints, hamming
from origin_worker.matching.geometry import Geometry, confirm
from origin_worker.matching.thresholds import Thresholds

_FAR = datetime.max


@dataclass(frozen=True)
class Item:
    """One verified sighting's image."""

    key: str
    fingerprints: Fingerprints
    image: Image.Image
    date_upper: datetime | None

    @property
    def area(self) -> int:
        return self.image.width * self.image.height


@dataclass
class Variant:
    members: list[Item]

    @property
    def representative(self) -> Item:
        """The best copy: the largest, then the earliest proven."""
        return sorted(
            self.members,
            key=lambda i: (-i.area, (i.date_upper or _FAR).replace(tzinfo=None), i.key),
        )[0]

    @property
    def earliest(self) -> datetime | None:
        dates = [i.date_upper for i in self.members if i.date_upper is not None]
        return min(dates) if dates else None


@dataclass(frozen=True)
class Edge:
    parent: int
    child: int
    kinds: list[str]
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass
class VariantGraph:
    variants: list[Variant]
    edges: list[Edge]


def _same_variant(a: Fingerprints, b: Fingerprints, thresholds: Thresholds) -> bool:
    nd = thresholds.near_duplicate
    if a.sha256 == b.sha256:
        return True
    if hamming(a.phash, b.phash) <= nd.phash_max:
        return True
    trusted = min(a.pdq_quality, b.pdq_quality) >= nd.pdq_min_quality
    return trusted and hamming(a.pdq, b.pdq) <= nd.pdq_max


def cluster(items: list[Item], thresholds: Thresholds) -> list[Variant]:
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _same_variant(items[i].fingerprints, items[j].fingerprints, thresholds):
                parent[find(i)] = find(j)
    groups: dict[int, list[Item]] = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)
    variants = [Variant(members) for members in groups.values()]
    # Stable order: earliest proven first, then by key.
    variants.sort(key=lambda v: ((v.earliest or _FAR).replace(tzinfo=None), v.representative.key))
    return variants


def _relation(
    parent: Variant, child: Variant, geometry: Geometry, thresholds: Thresholds
) -> tuple[list[str], str] | None:
    """Whether `child` (fitted into `parent`'s frame) derives from `parent`, and why."""
    t = thresholds.transform
    edits = geometry.edits(t)
    p, c = parent.representative, child.representative
    if geometry.covered_area < t.crop_area_max:
        return edits, f"covers {geometry.covered_area:.0%} of the parent's frame (crop)"
    # Same frame: smaller resolution derives from larger.
    if c.area < p.area * (1 - t.resize_tolerance):
        return [e for e in edits if e != "crop"] or ["resize"], "same frame at lower resolution"
    if p.area < c.area * (1 - t.resize_tolerance):
        return None
    # Same frame and size: time breaks the tie.
    if parent.earliest and child.earliest and parent.earliest < child.earliest:
        return edits or ["recompress"], "same frame and size; the parent was seen earlier"
    return None


def derive_edges(variants: list[Variant], thresholds: Thresholds) -> list[Edge]:
    best: dict[int, tuple[float, Edge]] = {}
    for pi, parent in enumerate(variants):
        for ci, child in enumerate(variants):
            if pi == ci:
                continue
            geometry = confirm(
                parent.representative.image, child.representative.image, thresholds.derivative
            )
            if geometry is None:
                continue
            relation = _relation(parent, child, geometry, thresholds)
            if relation is None:
                continue
            kinds, reason = relation
            kinds = [
                k for k in kinds if k in ("crop", "mirror", "resize", "overlay", "recompress")
            ] or ["recompress"]
            edge = Edge(
                parent=pi,
                child=ci,
                kinds=kinds,
                reason=reason,
                evidence={
                    "inliers": geometry.inliers,
                    "crop_box": list(geometry.crop_box),
                    "mirrored": geometry.mirrored,
                    "scale": round(geometry.scale, 4),
                    "overlay_fraction": round(geometry.overlay_fraction, 4),
                    "parent_sightings": [i.key for i in parent.members],
                    "child_sightings": [i.key for i in child.members],
                },
            )
            # Closest ancestor: the smallest parent frame that still contains the child.
            closeness = float(parent.representative.area)
            if ci not in best or closeness < best[ci][0]:
                best[ci] = (closeness, edge)
    edges = [edge for _, edge in best.values()]
    return _break_cycles(edges)


def _break_cycles(edges: list[Edge]) -> list[Edge]:
    """Drop any edge that would close a loop (possible only through near-equal frames)."""
    parent_of: dict[int, int] = {}
    kept: list[Edge] = []
    for edge in sorted(edges, key=lambda e: (e.child, e.parent)):
        node, seen = edge.parent, {edge.child}
        while node in parent_of and node not in seen:
            seen.add(node)
            node = parent_of[node]
        if node in seen:
            continue
        parent_of[edge.child] = edge.parent
        kept.append(edge)
    return kept


def build_variant_graph(items: list[Item], thresholds: Thresholds) -> VariantGraph:
    variants = cluster(items, thresholds)
    return VariantGraph(variants=variants, edges=derive_edges(variants, thresholds))
