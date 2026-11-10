"""Wayback Machine first captures, through the CDX server API.

"The archive has this URL as of date T" proves the page (or image) existed no later than T:
an upper bound for dating. The earliest capture with HTTP 200 is the strongest such bound.

The lookup is a provider like any other, so the ProviderRunner caches it (a first capture
never changes once it exists), records and replays it, retries it and logs every call. The
Internet Archive is free and keyless but rate-limits hard, so requests are spaced out.

CDX API: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from origin_core.fetch import USER_AGENT
from origin_core.providers.base import CandidateHit, ProviderError, RawResponse, UrlSubject

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
FIELDS = "timestamp,original,statuscode,mimetype,digest"
MIN_INTERVAL_S = 1.0


class _Pacer:
    """Process-wide spacing between requests to the archive."""

    def __init__(self, interval_s: float) -> None:
        self._interval = interval_s
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._last + self._interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()


_PACER = _Pacer(MIN_INTERVAL_S)


@dataclass(frozen=True)
class FirstCapture:
    url: str
    captured_at: datetime
    archive_url: str
    mimetype: str
    digest: str


def parse_cdx_timestamp(value: str) -> datetime:
    """CDX timestamps are UTC, `YYYYMMDDhhmmss`."""
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def archive_url(timestamp: str, original: str) -> str:
    """The replay URL for a capture; `id_` returns the archived bytes without the banner."""
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


class WaybackFirstCapture:
    """Adapter: the earliest successful capture of one URL."""

    name: str = "wayback"
    quota_key: str = "wayback"
    unit_cost: int = 0
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("Internet Archive (receives the URL, not the image)",)

    def params(self) -> dict[str, Any]:
        return {"fl": FIELDS, "filter": "statuscode:200", "limit": 1}

    async def fetch(self, subject: UrlSubject, client: httpx.AsyncClient) -> RawResponse:
        await _PACER.wait()
        query = {"url": subject.url, "output": "json", **self.params()}
        try:
            response = await client.get(
                CDX_ENDPOINT, params=query, headers={"User-Agent": USER_AGENT}, timeout=30
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"wayback request failed: {exc!r}", retryable=True) from exc
        if response.status_code in (429, 500, 502, 503, 504):
            raise ProviderError(f"wayback HTTP {response.status_code}", retryable=True)
        if response.status_code != 200:
            raise ProviderError(f"wayback HTTP {response.status_code}", retryable=False)
        return RawResponse(response.content)

    def parse(self, body: bytes) -> list[CandidateHit]:
        rows = cast(list[list[str]], json.loads(body) if body.strip() else [])
        if not rows:
            return []
        header, *data = rows
        hits: list[CandidateHit] = []
        for row in data:
            record = dict(zip(header, row, strict=False))
            hits.append(
                CandidateHit(
                    page_url=archive_url(record["timestamp"], record["original"]),
                    image_url=None,
                    provider_date=parse_cdx_timestamp(record["timestamp"]),
                    rank=len(hits) + 1,
                    title=None,
                    raw=record,
                )
            )
        return hits


def first_capture(hits: list[CandidateHit]) -> FirstCapture | None:
    """The earliest capture among parsed hits, or None if the URL was never archived."""
    dated = [h for h in hits if h.provider_date is not None and h.page_url]
    if not dated:
        return None
    best = min(dated, key=lambda h: cast(datetime, h.provider_date))
    return FirstCapture(
        url=str(best.raw.get("original", "")),
        captured_at=cast(datetime, best.provider_date),
        archive_url=cast(str, best.page_url),
        mimetype=str(best.raw.get("mimetype", "")),
        digest=str(best.raw.get("digest", "")),
    )
