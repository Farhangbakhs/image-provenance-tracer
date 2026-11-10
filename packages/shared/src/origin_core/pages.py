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
    images: list[str] = field(default_factory=list[str])
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


def parse_page(url: str, body: bytes) -> Page:
    html = body.decode("utf-8", errors="replace")
    try:
        doc: Any = _html.document_fromstring(html)
    except (ValueError, _etree.ParserError):
        return Page(url=url, title=None)

    title_nodes: list[Any] = doc.xpath("//meta[@property='og:title']/@content") or doc.xpath(
        "//title/text()"
    )
    title = str(title_nodes[0]).strip() if title_nodes else None

    images: list[str] = []

    def add(value: str | None) -> None:
        absolute = _absolute(url, value)
        if absolute and absolute not in images and not absolute.lower().endswith(".svg"):
            images.append(absolute)

    for key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image"):
        values: list[Any] = doc.xpath(f"//meta[@property='{key}' or @name='{key}']/@content")
        for value in values:
            add(str(value))
    imgs: list[Any] = doc.xpath("//img")
    for img in imgs:
        if _too_small(img):
            continue
        srcset = str(img.get("srcset") or "")
        if srcset:
            # The largest candidate in a srcset is listed last by convention.
            add(srcset.split(",")[-1].strip().split(" ")[0])
        add(img.get("src") or img.get("data-src"))

    return Page(
        url=url,
        title=title or None,
        images=images[:MAX_IMAGES],
        published=published_date(html, doc),
    )
