"""Variant clustering and derived-from edges on a real photo and edits of it."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from origin_core.ingest.hashes import fingerprint
from origin_core.ingest.validate import decode_rgb
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.variants import Item, build_variant_graph

PHOTO = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa" / "no-manifest.jpg"
T = load_thresholds()


def _item(key: str, image: Image.Image, day: int | None) -> Item:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    data = out.getvalue()
    decoded = decode_rgb(data)
    return Item(
        key,
        fingerprint(data, decoded),
        decoded,
        datetime(2024, 3, day, tzinfo=UTC) if day else None,
    )


def test_copies_cluster_and_edits_form_a_tree() -> None:
    photo = decode_rgb(PHOTO.read_bytes())
    w, h = photo.size
    crop = photo.crop((int(w * 0.15), int(h * 0.1), int(w * 0.85), int(h * 0.9)))
    captioned_crop = crop.copy()
    ImageDraw.Draw(captioned_crop).rectangle(
        (0, int(crop.height * 0.85), crop.width, crop.height), fill=(0, 0, 0)
    )
    items = [
        _item("original", photo, 3),
        _item("original-small", photo.resize((w // 2, h // 2)), 4),  # same variant as original
        _item("crop", crop, 5),
        _item("crop-recompressed", crop.resize((crop.width - 2, crop.height - 2)), 6),
        _item("mirror", ImageOps.mirror(photo), 7),
        _item("captioned-crop", captioned_crop, 8),
    ]

    graph = build_variant_graph(items, T)
    groups = sorted(sorted(i.key for i in v.members) for v in graph.variants)
    assert groups == [
        ["captioned-crop"],
        ["crop", "crop-recompressed"],
        ["mirror"],
        ["original", "original-small"],
    ]

    name = {i: v.representative.key for i, v in enumerate(graph.variants)}
    edges = {(name[e.parent], name[e.child]): e for e in graph.edges}
    # The crop comes from the full frame; the representative is the largest copy.
    assert ("original", "crop") in edges
    assert "crop" in edges[("original", "crop")].kinds
    # The mirror comes from the original.
    assert "mirror" in edges[("original", "mirror")].kinds
    # The captioned crop's closest ancestor is the crop, not the full frame.
    assert ("crop", "captioned-crop") in edges
    assert ("original", "captioned-crop") not in edges
    # A forest: every variant has at most one parent, and nothing derives from itself.
    children = [e.child for e in graph.edges]
    assert len(children) == len(set(children))
    assert all(e.parent != e.child for e in graph.edges)
    # Every edge says why it exists.
    assert all(e.reason and e.evidence["inliers"] > 0 for e in graph.edges)


def test_unrelated_images_get_no_edges() -> None:
    photo = decode_rgb(PHOTO.read_bytes())
    other = decode_rgb((PHOTO.parent / "signed-test-cert.jpg").read_bytes())
    graph = build_variant_graph([_item("a", photo, 1), _item("b", other, 2)], T)
    assert len(graph.variants) == 2
    assert graph.edges == []
