"""Where watchlist photos come from: the public web preview, or (optionally) the Telethon API.

Both sources yield the same thing, a `ChannelPhoto`: one photo of one public post with its
platform time, text and forward header, plus the photo bytes. Both are deliberately slow: one
request every `interval_s` seconds, and they stop early rather than push through throttling.

PreviewSource needs no account. It reads t.me/s/<channel> through ORIGIN's hardened fetcher,
newest page first, following `?before=` to older pages, or `?q=` to search.

TelethonSource needs the owner's own API id and hash and a logged-in session file. Telethon is
an optional dependency (`uv sync --extra telegram`) and is imported only when this source is
used. Telethon sleeps through flood waits up to its threshold; longer ones end the collection.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

from origin_core.fetch import (
    IMAGE_POLICY,
    PAGE_POLICY,
    FetchBlocked,
    Fetcher,
    FetchFailed,
    FetchResult,
)
from origin_core.telegram.preview import (
    Forward,
    PreviewPost,
    channel_page_url,
    embed_url,
    parse_preview,
)

log = structlog.get_logger(__name__)

#: Longest wait ORIGIN accepts from a 429 or a flood wait before giving up on the channel.
MAX_BACKOFF_S = 60.0


@dataclass(frozen=True)
class ChannelPhoto:
    channel: str
    message_id: int
    photo_index: int
    posted_at: datetime
    text: str
    forwarded_from: Forward | None
    image_url: str
    data: bytes
    content_type: str
    fetched_at: datetime
    http_status: int | None = None
    http_headers: dict[str, str] | None = None


class Throttled(Exception):
    """Telegram asked ORIGIN to slow down for longer than it is willing to wait."""


class PhotoSource(Protocol):
    via: str

    def photos(
        self,
        channel: str,
        *,
        newer_than: int | None = None,
        query: str | None = None,
        max_pages: int = 5,
    ) -> AsyncIterator[ChannelPhoto]: ...

    async def post(self, channel: str, message_id: int) -> PreviewPost | None:
        """One public post's time, text and forward header; None if it cannot be read."""
        ...


class Pacer:
    """At most one request per interval, across everything one source does."""

    def __init__(
        self,
        interval_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    @property
    def interval_s(self) -> float:
        return self._interval

    async def wait(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            await self._sleep(self._interval - (now - self._last))
        self._last = self._clock()

    async def back_off(self, seconds: float) -> None:
        if seconds > MAX_BACKOFF_S:
            raise Throttled(f"Telegram asked to wait {seconds:.0f}s")
        await self._sleep(seconds)


def _retry_after(headers: dict[str, str]) -> float:
    value = headers.get("retry-after", "")
    if value.strip().isdigit():
        return float(value)
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return MAX_BACKOFF_S + 1


@dataclass
class PreviewSource:
    fetcher: Fetcher
    pacer: Pacer
    via: str = "preview"

    async def _get(self, url: str, *, image: bool) -> FetchResult:
        for _ in range(2):
            await self.pacer.wait()
            result = await self.fetcher.get(url, IMAGE_POLICY if image else PAGE_POLICY)
            if result.status != 429:
                return result
            await self.pacer.back_off(_retry_after(result.headers))
        raise Throttled(f"still throttled after backing off: {url}")

    async def post(self, channel: str, message_id: int) -> PreviewPost | None:
        try:
            result = await self._get(embed_url(channel, message_id), image=False)
        except (FetchBlocked, FetchFailed, Throttled) as exc:
            log.info("telegram_post_fetch_failed", channel=channel, post=message_id, error=str(exc))
            return None
        if result.status != 200:
            return None
        for post in parse_preview(result.body).posts:
            if post.channel.lower() == channel.lower() and post.message_id == message_id:
                return post
        return None

    async def photos(
        self,
        channel: str,
        *,
        newer_than: int | None = None,
        query: str | None = None,
        max_pages: int = 5,
    ) -> AsyncIterator[ChannelPhoto]:
        before: int | None = None
        for _ in range(max_pages):
            url = channel_page_url(channel, before=before, query=query)
            try:
                listing = await self._get(url, image=False)
            except (FetchBlocked, FetchFailed) as exc:
                log.info("telegram_preview_page_failed", channel=channel, error=str(exc))
                return
            if listing.status != 200:
                log.info("telegram_preview_page_failed", channel=channel, status=listing.status)
                return
            page = parse_preview(listing.body)
            for post in reversed(page.posts):  # newest first
                if newer_than is not None and post.message_id <= newer_than:
                    return
                if post.channel.lower() != channel.lower() or post.posted_at is None:
                    continue
                for index, photo_url in enumerate(post.photos):
                    try:
                        result = await self._get(photo_url, image=True)
                    except (FetchBlocked, FetchFailed) as exc:
                        log.info("telegram_photo_fetch_failed", url=photo_url, error=str(exc))
                        continue
                    if result.status != 200:
                        continue
                    yield ChannelPhoto(
                        channel=post.channel,
                        message_id=post.message_id,
                        photo_index=index,
                        posted_at=post.posted_at,
                        text=post.text,
                        forwarded_from=post.forwarded_from,
                        image_url=result.final_url,
                        data=result.body,
                        content_type=result.content_type or "image/jpeg",
                        fetched_at=result.fetched_at,
                        http_status=result.status,
                        http_headers=result.headers,
                    )
            # Older pages hold only ids below `older`; stop if those are all collected already.
            if page.older is None or (newer_than is not None and page.older <= newer_than + 1):
                return
            before = page.older


class TelethonSource:
    """Photo messages through the Telegram API with the owner's own app and session.

    Not exercised against Telegram in ORIGIN's tests (that needs the owner's login); the
    tests drive it with a stand-in client that has Telethon's documented interface.
    """

    via: str = "api"

    def __init__(self, client: Any, pacer: Pacer, photo_filter: Any) -> None:
        self._client = client
        self._pacer = pacer
        self._filter = photo_filter
        self._names: dict[int, str | None] = {}

    @classmethod
    def connect(
        cls, *, api_id: int, api_hash: str, session: Path, interval_s: float
    ) -> TelethonSource:
        try:
            telethon: Any = importlib.import_module("telethon")
            types: Any = importlib.import_module("telethon.tl.types")
        except ImportError as exc:
            raise SystemExit("Telethon is not installed: uv sync --extra telegram") from exc
        session.parent.mkdir(parents=True, exist_ok=True)
        client = telethon.TelegramClient(
            str(session), api_id, api_hash, flood_sleep_threshold=int(MAX_BACKOFF_S)
        )
        return cls(client, Pacer(interval_s), types.InputMessagesFilterPhotos)

    @property
    def client(self) -> Any:
        return self._client

    async def _channel_username(self, peer: Any) -> str | None:
        channel_id = getattr(peer, "channel_id", None)
        if channel_id is None:
            return None  # a user or a hidden sender: not resolved, never profiled
        if channel_id not in self._names:
            await self._pacer.wait()
            try:
                entity = await self._client.get_entity(peer)
                self._names[channel_id] = getattr(entity, "username", None)
            except (ValueError, TypeError):
                self._names[channel_id] = None
        return self._names[channel_id]

    async def _forward(self, header: Any) -> Forward | None:
        if header is None:
            return None
        channel = await self._channel_username(getattr(header, "from_id", None))
        post = getattr(header, "channel_post", None)
        return Forward(
            getattr(header, "from_name", None),
            channel,
            int(post) if channel and isinstance(post, int) else None,
        )

    async def post(self, channel: str, message_id: int) -> PreviewPost | None:
        await self._pacer.wait()
        message = await self._client.get_messages(channel, ids=message_id)
        if message is None or message.date is None:
            return None
        return PreviewPost(
            channel=channel,
            message_id=message_id,
            posted_at=message.date.astimezone(UTC),
            text=message.message or "",
            forwarded_from=await self._forward(message.fwd_from),
        )

    async def photos(
        self,
        channel: str,
        *,
        newer_than: int | None = None,
        query: str | None = None,
        max_pages: int = 5,
    ) -> AsyncIterator[ChannelPhoto]:
        await self._pacer.wait()
        messages = self._client.iter_messages(
            channel,
            limit=max_pages * 20,
            min_id=newer_than or 0,
            search=query,
            filter=self._filter,
            wait_time=self._pacer.interval_s,
        )
        async for message in messages:
            if getattr(message, "photo", None) is None or message.date is None:
                continue
            await self._pacer.wait()
            data = await self._client.download_media(message, bytes)
            if not isinstance(data, bytes):
                continue
            yield ChannelPhoto(
                channel=channel,
                message_id=int(message.id),
                photo_index=0,
                posted_at=message.date.astimezone(UTC),
                text=message.message or "",
                forwarded_from=await self._forward(message.fwd_from),
                image_url=f"https://t.me/{channel}/{int(message.id)}",
                data=data,
                content_type="image/jpeg",
                fetched_at=datetime.now(UTC),
            )
