"""Reading a fetched web page: its title, the images on it, and the date it claims.

Page HTML is untrusted input: it is parsed, never executed, and nothing in it is treated as an
instruction. Its stated publication date is a *claim* (medium confidence at best), used by the
dating rule only where it agrees with the proven bounds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urljoin, urlsplit

import lxml.etree
import lxml.html
from htmldate import find_date  # pyright: ignore[reportMissingTypeStubs]

# lxml's stubs do not cover the element API used here; it is typed at this boundary.
_html: Any = lxml.html
_etree: Any = lxml.etree  # pyright: ignore[reportUnknownVariableType]

MAX_IMAGES = 12
#: Images smaller than this on a declared side are icons, avatars or tracking pixels.
MIN_DECLARED_SIDE = 64
PUBLISHED_META = (
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "pubdate",
    "publishdate",
    "dc.date.issued",
    "date",
)


@dataclass(frozen=True)
class PublishedDate:
    value: datetime
    #: Where it came from: "meta:article:published_time", "json-ld", "htmldate".
    source: str
    #: True when only a calendar day was stated (time set to 00:00 UTC).
    day_only: bool


@dataclass(frozen=True)
class Page:
    url: str
    title: str | None
    #: The page's own summary (og:description, twitter:description or meta description). Social
    #: pages keep their post text here when the body is a login wall.
    description: str | None = None
    images: list[str] = field(default_factory=list[str])
    #: Sizes the page itself declares for some of its images (width, height).
    image_sizes: dict[str, tuple[int, int]] = field(default_factory=dict[str, tuple[int, int]])
    published: PublishedDate | None = None


def _absolute(base: str, value: str | None) -> str | None:
    if not value:
        return None
    url = urljoin(base, value.strip())
    return url if urlsplit(url).scheme in ("http", "https") else None


def _parse_datetime(text: str) -> tuple[datetime, bool] | None:
    raw = text.strip()
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    day_only = len(raw) <= 10
    if value.tzinfo is None:
        # A stated date without a zone: keep the day, and say so.
        value = value.replace(tzinfo=UTC)
        day_only = day_only or value.time() == datetime.min.time()
    return value.astimezone(UTC), day_only


def _json_ld_dates(doc: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            mapping = cast(dict[str, Any], node)
            value = mapping.get("datePublished")
            if isinstance(value, str):
                found.append(value)
            for child in mapping.values():
                walk(child)
        elif isinstance(node, list):
            for child in cast(list[Any], node):
                walk(child)

    for script in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            walk(json.loads(script.text_content()))
        except ValueError:
            continue
    return found


def published_date(html: str, doc: Any) -> PublishedDate | None:
    for meta in doc.xpath("//meta[@content]"):
        key = (meta.get("property") or meta.get("name") or meta.get("itemprop") or "").lower()
        if key in PUBLISHED_META:
            parsed = _parse_datetime(meta.get("content", ""))
            if parsed:
                return PublishedDate(parsed[0], f"meta:{key}", parsed[1])
    for value in _json_ld_dates(doc):
        parsed = _parse_datetime(value)
        if parsed:
            return PublishedDate(parsed[0], "json-ld", parsed[1])
    found: str | None = find_date(
        html, original_date=True, extensive_search=False, outputformat="%Y-%m-%d"
    )
    if found:
        parsed = _parse_datetime(found)
        if parsed:
            return PublishedDate(parsed[0], "htmldate", True)
    return None


def _too_small(img: Any) -> bool:
    for attribute in ("width", "height"):
        value = str(img.get(attribute) or "").strip().removesuffix("px")
        if value.isdigit() and int(value) < MIN_DECLARED_SIDE:
            return True
    return False


def _first_meta(doc: Any, keys: tuple[str, ...]) -> str | None:
    """The first non-empty meta content among these property or name keys, in order."""
    for key in keys:
        values: list[Any] = doc.xpath(f"//meta[@property='{key}' or @name='{key}']/@content")
        for value in values:
            text = " ".join(str(value).split())
            if text:
                return text
    return None


def _declared_size(img: Any) -> tuple[int, int] | None:
    sides: list[int] = []
    for attribute in ("width", "height"):
        value = str(img.get(attribute) or "").strip().removesuffix("px")
        if not value.isdigit():
            return None
        sides.append(int(value))
    return (sides[0], sides[1]) if all(sides) else None


def _size_score(size: tuple[int, int] | None, prefer: tuple[int, int]) -> int:
    """2 for the size the provider reported, 1 for the same shape, else 0."""
    if size is None:
        return 0
    (w, h), (pw, ph) = size, prefer
    if abs(w - pw) <= 2 and abs(h - ph) <= 2:
        return 2
    return 1 if abs(w / h - pw / ph) <= 0.01 * (pw / ph) else 0


def parse_page(url: str, body: bytes, *, prefer: tuple[int, int] | None = None) -> Page:
    """Read a page. `prefer` is the size of the image a provider says it matched: the page's own
    og/twitter images still come first, then the other images whose declared size matches it,
    so the matching one is not lost behind the cap on how many images are fetched."""
    html = body.decode("utf-8", errors="replace")
    try:
        doc: Any = _html.document_fromstring(html)
    except (ValueError, _etree.ParserError):
        return Page(url=url, title=None)

    title_nodes: list[Any] = doc.xpath("//meta[@property='og:title']/@content") or doc.xpath(
        "//title/text()"
    )
    title = str(title_nodes[0]).strip() if title_nodes else None

    description = _first_meta(doc, ("og:description", "twitter:description", "description"))

    images: list[str] = []
    sizes: dict[str, tuple[int, int]] = {}
    declared = {side: _first_meta(doc, (f"og:image:{side}",)) for side in ("width", "height")}

    def add(value: str | None, size: tuple[int, int] | None = None) -> None:
        absolute = _absolute(url, value)
        if absolute and absolute not in images and not absolute.lower().endswith(".svg"):
            images.append(absolute)
            if size is not None:
                sizes[absolute] = size

    for key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image"):
        values: list[Any] = doc.xpath(f"//meta[@property='{key}' or @name='{key}']/@content")
        for value in values:
            og_size = (
                (int(declared["width"] or 0), int(declared["height"] or 0))
                if key == "og:image"
                and (declared["width"] or "").isdigit()
                and (declared["height"] or "").isdigit()
                else None
            )
            add(str(value), og_size)
    from_meta = len(images)
    imgs: list[Any] = doc.xpath("//img")
    for img in imgs:
        if _too_small(img):
            continue
        size = _declared_size(img)
        srcset = str(img.get("srcset") or "")
        if srcset:
            # The largest candidate in a srcset is listed last by convention.
            add(srcset.split(",")[-1].strip().split(" ")[0])
        add(img.get("src") or img.get("data-src"), size)
    if prefer is not None:
        # Stable: images the page does not size keep their order, after the ones that match.
        rest = sorted(images[from_meta:], key=lambda u: -_size_score(sizes.get(u), prefer))
        images[from_meta:] = rest

    return Page(
        url=url,
        title=title or None,
        description=description,
        images=images[:MAX_IMAGES],
        image_sizes={u: s for u, s in sizes.items() if u in images[:MAX_IMAGES]},
        published=published_date(html, doc),
    )


MAX_TEXT_CHARS = 4000

#: A page's extracted text shorter than this is taken to be boilerplate (a login wall, a cookie
#: notice), and its own og:description is used instead when it says more.
MIN_ARTICLE_CHARS = 80


def caption_for(url: str, body: bytes, image_url: str) -> str | None:
    """The alt text and figure caption attached to `image_url` on the page, if any."""
    try:
        doc: Any = _html.document_fromstring(body.decode("utf-8", errors="replace"))
    except (ValueError, _etree.ParserError):
        return None
    target = urlsplit(image_url).path
    parts: list[str] = []
    imgs: list[Any] = doc.xpath("//img")
    for img in imgs:
        sources = [img.get("src"), img.get("data-src"), *str(img.get("srcset") or "").split(",")]
        if not any(
            s and urlsplit(urljoin(url, s.strip().split(" ")[0])).path == target for s in sources
        ):
            continue
        if img.get("alt"):
            parts.append(str(img.get("alt")).strip())
        figure: list[Any] = img.xpath("ancestor::figure[1]//figcaption")
        parts.extend(" ".join(f.text_content().split()) for f in figure)
        break
    joined = " ".join(p for p in parts if p)
    return joined or None


def main_text(body: bytes) -> str | None:
    """The page's main article text (boilerplate, navigation and comments removed)."""
    from trafilatura import extract  # pyright: ignore[reportMissingTypeStubs]

    text: str | None = extract(
        body.decode("utf-8", errors="replace"),
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text:
        return None
    return text[:MAX_TEXT_CHARS]


def page_text(page: Page, extracted: str | None) -> str | None:
    """The text a claim is read from: the article body, or for social pages the post summary.

    Instagram, Facebook, X and Threads serve a login wall as the body, but keep the post's
    caption in og:title and og:description. When the extracted body is missing or boilerplate,
    that description is used, so a claim can still be read from the post.
    """
    description = (page.description or "")[:MAX_TEXT_CHARS] or None
    if description and (extracted is None or len(extracted) < MIN_ARTICLE_CHARS):
        if extracted and extracted not in description:
            return f"{extracted}\n{description}"[:MAX_TEXT_CHARS]
        return description
    return extracted
