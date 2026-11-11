"""Matching eval: does ORIGIN recognise edited copies, and does it refuse unrelated photos?

Source photos are scikit-image's bundled sample images (installed with the `eval` dependency
group, never copied into this repository). Each is edited in ways reposts are edited; every
edited copy must be classified as related, in an acceptable class. Every other photo, including
a stereo pair of the same scene taken from a different position, must be classified unrelated.

Everything is generated deterministically from the source images, so the eval needs no network
after the first install and gives the same numbers on every run.
"""

from __future__ import annotations

import importlib.util
import io
import statistics
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from origin_core.enums import MatchClass
from origin_core.ingest.hashes import fingerprint
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.classify import MatchResult, Side, classify
from origin_worker.matching.thresholds import Thresholds

# Photographs and photographic textures; synthetic test patterns are left out.
SOURCES = (
    "astronaut.png",
    "camera.png",
    "chelsea.png",
    "coffee.png",
    "coins.png",
    "hubble_deep_field.jpg",
    "rocket.jpg",
    "retina.jpg",
    "ihc.png",
    "moon.png",
    "brick.png",
    "grass.png",
    "gravel.png",
    "page.png",
    "text.png",
    "clock_motion.png",
    "motorcycle_left.png",
    "motorcycle_right.png",
)

# The same scene photographed from a slightly different position: the hardest negative.
HARD_NEGATIVES = (("motorcycle_left.png", "motorcycle_right.png"),)

ND = MatchClass.NEAR_DUPLICATE
DER = MatchClass.DERIVATIVE


def source_dir() -> Path:
    """scikit-image's bundled sample photographs (installed by the `eval` dependency group)."""
    spec = importlib.util.find_spec("skimage")
    if spec is None or spec.origin is None:
        raise SystemExit("scikit-image is missing: run `make eval` (uv run --group eval ...)")
    return Path(spec.origin).parent / "data"


def _encode(image: Image.Image, fmt: str = "JPEG", quality: int = 90) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, quality=quality)
    return out.getvalue()


def _scaled(image: Image.Image, factor: float) -> Image.Image:
    return image.resize((max(1, int(image.width * factor)), max(1, int(image.height * factor))))


def _crop(image: Image.Image, keep: float, dx: float = 0.5, dy: float = 0.5) -> Image.Image:
    w, h = image.size
    cw, ch = int(w * keep), int(h * keep)
    left, top = int((w - cw) * dx), int((h - ch) * dy)
    return image.crop((left, top, left + cw, top + ch))


def _caption(image: Image.Image) -> Image.Image:
    out = _crop(image, 0.85)
    ImageDraw.Draw(out).rectangle(
        (0, int(out.height * 0.82), out.width, out.height), fill=(0, 0, 0)
    )
    return out


def _watermark(image: Image.Image) -> Image.Image:
    out = image.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    draw.rectangle((int(w * 0.6), int(h * 0.88), w, h), fill=(255, 255, 255))
    draw.text((int(w * 0.62), int(h * 0.9)), "@viral_reposts", fill=(0, 0, 0))
    return out


def _letterbox(image: Image.Image) -> Image.Image:
    w, h = image.size
    canvas = Image.new("RGB", (int(w * 1.0), int(h * 1.6)), (255, 255, 255))
    canvas.paste(image, (0, int(h * 0.3)))
    return canvas


@dataclass(frozen=True)
class Edit:
    name: str
    describe: str
    accept: frozenset[MatchClass]
    make: Callable[[Image.Image], bytes]


EDITS: tuple[Edit, ...] = (
    Edit("resize", "scaled to 50%", frozenset({ND}), lambda im: _encode(_scaled(im, 0.5))),
    Edit("recompress", "JPEG quality 30", frozenset({ND}), lambda im: _encode(im, quality=30)),
    Edit("webp", "WebP quality 50", frozenset({ND}), lambda im: _encode(im, "WEBP", 50)),
    Edit("mirror", "mirrored", frozenset({ND, DER}), lambda im: _encode(ImageOps.mirror(im))),
    Edit(
        "rotate90",
        "rotated 90°",
        frozenset({ND, DER}),
        lambda im: _encode(im.rotate(90, expand=True)),
    ),
    Edit(
        "grey",
        "converted to greyscale",
        frozenset({ND, DER}),
        lambda im: _encode(ImageOps.grayscale(im).convert("RGB")),
    ),
    Edit(
        "colour",
        "brightness +25%, contrast +30%",
        frozenset({ND, DER}),
        lambda im: _encode(
            ImageEnhance.Contrast(ImageEnhance.Brightness(im).enhance(1.25)).enhance(1.3)
        ),
    ),
    Edit("crop80", "centre crop to 80%", frozenset({DER}), lambda im: _encode(_crop(im, 0.8))),
    Edit(
        "crop60",
        "off-centre crop to 60%",
        frozenset({DER}),
        lambda im: _encode(_crop(im, 0.6, 0.2, 0.7)),
    ),
    Edit(
        "caption", "cropped, with a caption bar", frozenset({DER}), lambda im: _encode(_caption(im))
    ),
    Edit(
        "watermark",
        "account watermark in a corner",
        frozenset({ND, DER}),
        lambda im: _encode(_watermark(im)),
    ),
    Edit(
        "letterbox",
        "padded into a tall frame (screenshot)",
        frozenset({DER}),
        lambda im: _encode(_letterbox(im)),
    ),
    Edit(
        "rotate5",
        "rotated 5° with expanded frame",
        frozenset({ND, DER}),
        lambda im: _encode(im.rotate(5, expand=True, fillcolor=(0, 0, 0))),
    ),
    Edit(
        "small_crop_caption",
        "scaled to 40%, cropped and captioned",
        frozenset({DER}),
        lambda im: _encode(_caption(_scaled(im, 0.4))),
    ),
)


@dataclass(frozen=True)
class Trial:
    kind: str  # "edit" or "negative"
    source: str
    other: str  # the edit name, or the other source for a negative
    accept: frozenset[MatchClass] | None  # None: must be unrelated
    result: MatchResult

    @property
    def related(self) -> bool:
        return self.result.match_class is not None

    @property
    def correct(self) -> bool:
        if self.accept is None:
            return not self.related
        return self.result.match_class in self.accept


def _side(data: bytes, embedder: SSCDEmbedder) -> Side:
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
    return Side(fingerprint(data, image), embedder.embed_sync(image), image)


@dataclass(frozen=True)
class Pair:
    kind: str  # "edit" or "negative"
    source: str
    other: str  # the edit name, or the other source for a negative
    accept: frozenset[MatchClass] | None  # None: must be unrelated
    query: Side
    candidate: Side


def prepare(embedder: SSCDEmbedder, progress: Callable[[str], None] = lambda _: None) -> list[Pair]:
    """Fingerprint and embed every query and candidate once; classification is cheap after."""
    root = source_dir()
    originals: dict[str, Image.Image] = {}
    queries: dict[str, Side] = {}
    for name in SOURCES:
        with Image.open(root / name) as opened:
            originals[name] = opened.convert("RGB")
        queries[name] = _side(_encode(originals[name], quality=95), embedder)
    pairs: list[Pair] = []
    for name, image in originals.items():
        for edit in EDITS:
            candidate = _side(edit.make(image), embedder)
            pairs.append(Pair("edit", name, edit.name, edit.accept, queries[name], candidate))
        progress(f"prepared {name}")
    for a, b in _negative_pairs():
        pairs.append(Pair("negative", a, b, None, queries[a], queries[b]))
    return pairs


def run(pairs: list[Pair], thresholds: Thresholds) -> list[Trial]:
    return [
        Trial(p.kind, p.source, p.other, p.accept, classify(p.query, p.candidate, thresholds))
        for p in pairs
    ]


def _negative_pairs() -> Iterator[tuple[str, str]]:
    for a in SOURCES:
        for b in SOURCES:
            if a != b:
                yield a, b


@dataclass(frozen=True)
class Summary:
    edits: int
    edits_related: int
    edits_correct: int
    negatives: int
    false_positives: int
    by_edit: dict[str, tuple[int, int, int]]  # name -> (total, related, correct class)
    sscd_related_min: float
    sscd_negative_max: float
    sscd_negative_p99: float


def summarise(trials: list[Trial]) -> Summary:
    edits = [t for t in trials if t.kind == "edit"]
    negatives = [t for t in trials if t.kind == "negative"]
    by_edit: dict[str, tuple[int, int, int]] = {}
    for edit in EDITS:
        mine = [t for t in edits if t.other == edit.name]
        by_edit[edit.name] = (len(mine), sum(t.related for t in mine), sum(t.correct for t in mine))
    neg_scores = sorted(t.result.sscd_cosine for t in negatives)
    p99 = neg_scores[min(len(neg_scores) - 1, int(len(neg_scores) * 0.99))] if neg_scores else 0.0
    related_scores = [t.result.sscd_cosine for t in edits if t.related]
    return Summary(
        edits=len(edits),
        edits_related=sum(t.related for t in edits),
        edits_correct=sum(t.correct for t in edits),
        negatives=len(negatives),
        false_positives=sum(t.related for t in negatives),
        by_edit=by_edit,
        sscd_related_min=min(related_scores) if related_scores else 0.0,
        sscd_negative_max=neg_scores[-1] if neg_scores else 0.0,
        sscd_negative_p99=p99,
    )


def median_sscd(trials: list[Trial], edit: str) -> float:
    return statistics.median(t.result.sscd_cosine for t in trials if t.other == edit)
