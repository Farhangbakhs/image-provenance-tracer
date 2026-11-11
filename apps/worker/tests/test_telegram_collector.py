"""Telegram watchlist collection: pacing, the preview source, the Telethon source, the index.

SYNTHETIC: channel pages are generated here in the t.me/s markup (see
origin_core.telegram.preview), and the Telethon client is a stand-in with Telethon's
documented interface (iter_messages, download_media(message, bytes), get_entity). No request
leaves the process.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from origin_core.db.models import TelegramChannel, TelegramPost
from origin_core.db.session import make_sessionmaker
from origin_core.fetch import Fetcher
from origin_core.storage import FilesystemBlobStore
from origin_core.telegram.preview import Forward
from origin_worker.telegram.collector import Collector, add_channel
from origin_worker.telegram.sources import (
    ChannelPhoto,
    Pacer,
    PreviewSource,
    TelethonSource,
    Throttled,
)

PUBLIC_IP = "149.154.167.99"


def _jpeg(colour: tuple[int, int, int], size: tuple[int, int] = (96, 72)) -> bytes:
    out = io.BytesIO()
    image = Image.new("RGB", size, colour)
    for x in range(0, size[0], 8):
        image.putpixel((x, x % size[1]), (255 - colour[0], 0, 0))
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _post(channel: str, number: int, when: str, photos: list[str], forward: str = "") -> str:
    wraps = "".join(
        f'<a class="tgme_widget_message_photo_wrap" href="https://t.me/{channel}/{number}" '
        f"style=\"background-image:url('{url}')\"></a>"
        for url in photos
    )
    return (
        f'<div class="tgme_widget_message js-widget_message" data-post="{channel}/{number}">'
        f"{forward}{wraps}"
        f'<div class="tgme_widget_message_text">post {number}</div>'
        f'<a class="tgme_widget_message_date" href="https://t.me/{channel}/{number}">'
        f'<time datetime="{when}">t</time></a></div>'
    )


def _page(posts: list[str], before: int | None) -> bytes:
    more = f'<div class="tme_messages_more" data-before="{before}"></div>' if before else ""
    return f"<html><body>{more}{''.join(posts)}</body></html>".encode()


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _pacer(clock: FakeClock, interval: float = 3.0) -> Pacer:
    return Pacer(interval, clock=clock.clock, sleep=clock.sleep)


async def test_pacer_spaces_requests_and_refuses_long_waits() -> None:
    clock = FakeClock()
    pacer = _pacer(clock)
    await pacer.wait()
    clock.now += 1.0
    await pacer.wait()
    await pacer.wait()
    assert clock.slept == [2.0, 3.0]
    await pacer.back_off(10)
    with pytest.raises(Throttled):
        await pacer.back_off(600)


def _web() -> dict[str, httpx.Response]:
    newest = _page(
        [
            _post("demo_wire", 11, "2024-10-30T09:00:00+00:00", ["https://cdn.telesco.pe/b.jpg"]),
            _post("demo_wire", 12, "2024-10-30T10:00:00+00:00", []),
        ],
        before=11,
    )
    older = _page(
        [
            _post(
                "demo_wire",
                10,
                "2024-10-29T18:02:00+00:00",
                ["https://cdn.telesco.pe/a.jpg", "https://cdn.telesco.pe/gone.jpg"],
                forward='<div class="tgme_widget_message_forwarded_from">Forwarded from '
                '<a class="tgme_widget_message_forwarded_from_name" '
                'href="https://t.me/first_hand/7">First Hand</a></div>',
            )
        ],
        before=None,
    )
    jpeg = {"content-type": "image/jpeg"}
    return {
        "/s/demo_wire": httpx.Response(200, content=newest),
        "/s/demo_wire?before=11": httpx.Response(200, content=older),
        "/b.jpg": httpx.Response(200, headers=jpeg, content=_jpeg((40, 90, 160))),
        "/a.jpg": httpx.Response(200, headers=jpeg, content=_jpeg((160, 90, 40))),
        "/gone.jpg": httpx.Response(404),
    }


def _fetcher(web: dict[str, httpx.Response], seen: list[str]) -> Fetcher:
    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC_IP]

    def serve(request: httpx.Request) -> httpx.Response:
        key = request.url.raw_path.decode()
        seen.append(f"{request.headers['host']}{key}")
        return web.get(key, httpx.Response(404))

    return Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))


async def test_preview_source_walks_pages_newest_first_and_fetches_photos() -> None:
    seen: list[str] = []
    clock = FakeClock()
    source = PreviewSource(_fetcher(_web(), seen), _pacer(clock))
    photos = [p async for p in source.photos("demo_wire")]
    assert [(p.message_id, p.photo_index) for p in photos] == [(11, 0), (10, 0)]
    first, second = photos
    assert first.posted_at == datetime(2024, 10, 30, 9, tzinfo=UTC)
    assert second.forwarded_from == Forward("First Hand", "first_hand", 7)
    assert second.image_url == "https://cdn.telesco.pe/a.jpg"
    assert seen[0] == "t.me/s/demo_wire" and "t.me/s/demo_wire?before=11" in seen
    # Every request after the first waited its turn.
    assert len(clock.slept) == len(seen) - 1


async def test_preview_source_stops_at_the_newest_collected_post() -> None:
    seen: list[str] = []
    source = PreviewSource(_fetcher(_web(), seen), _pacer(FakeClock()))
    photos = [p async for p in source.photos("demo_wire", newer_than=10)]
    assert [p.message_id for p in photos] == [11]
    assert "t.me/s/demo_wire?before=11" not in seen


async def test_preview_source_backs_off_on_429_then_gives_up() -> None:
    web = {"/s/demo_wire": httpx.Response(429, headers={"retry-after": "5"})}
    clock = FakeClock()
    source = PreviewSource(_fetcher(web, []), _pacer(clock))
    with pytest.raises(Throttled):
        _ = [p async for p in source.photos("demo_wire")]
    assert 5.0 in clock.slept


@dataclass
class FakePeer:
    channel_id: int


@dataclass
class FakeForward:
    from_id: Any
    channel_post: int | None
    from_name: str | None = None


@dataclass
class FakeMessage:
    id: int
    date: datetime
    message: str
    photo: object | None
    fwd_from: FakeForward | None = None


class FakeTelethon:
    def __init__(self, messages: list[FakeMessage]) -> None:
        self.messages = messages
        self.calls: list[dict[str, Any]] = []

    def iter_messages(self, entity: str, **kwargs: Any) -> Any:
        self.calls.append({"entity": entity, **kwargs})

        async def gen() -> Any:
            for message in self.messages:
                if message.id > kwargs.get("min_id", 0):
                    yield message

        return gen()

    async def download_media(self, message: FakeMessage, file: type) -> bytes:
        assert file is bytes
        return _jpeg((message.id * 10 % 255, 50, 50))

    async def get_entity(self, peer: FakePeer) -> Any:
        return type("Channel", (), {"username": f"origin_{peer.channel_id}"})()


async def test_telethon_source_reads_photo_messages_and_forward_headers() -> None:
    when = datetime(2024, 10, 29, 18, tzinfo=UTC)
    client = FakeTelethon(
        [
            FakeMessage(21, when, "with photo", object(), FakeForward(FakePeer(77), 5)),
            FakeMessage(22, when, "no photo", None),
            FakeMessage(23, when, "hidden sender", object(), FakeForward(None, None, "Someone")),
        ]
    )
    source = TelethonSource(client, _pacer(FakeClock(), 1.0), photo_filter="PHOTOS")
    photos = [p async for p in source.photos("demo_wire", newer_than=20, query="flood")]
    assert [p.message_id for p in photos] == [21, 23]
    assert photos[0].forwarded_from == Forward(None, "origin_77", 5)
    assert photos[1].forwarded_from == Forward("Someone")
    assert photos[0].image_url == "https://t.me/demo_wire/21"
    call = client.calls[0]
    assert call["min_id"] == 20 and call["search"] == "flood" and call["filter"] == "PHOTOS"


class FakeEmbedder:
    model_id = "fake@0000000"

    async def embed(self, image: Image.Image) -> list[float]:
        mean = image.convert("RGB").resize((1, 1)).tobytes()
        return [float(v) + 1 for v in mean] + [0.0] * 509


@pytest.mark.db
async def test_collector_indexes_watchlist_photos_once(
    db_engine: AsyncEngine, tmp_path: Path
) -> None:
    sessions = make_sessionmaker(db_engine)
    channel = await add_channel(sessions, "https://t.me/s/demo_wire", added_by="test", note=None)
    assert channel == "demo_wire"
    collector = Collector(
        sessions=sessions,
        blobs=FilesystemBlobStore(tmp_path),
        embedder=FakeEmbedder(),
        max_pixels=50_000_000,
    )
    source = PreviewSource(_fetcher(_web(), []), _pacer(FakeClock()))
    report = await collector.collect(source, "demo_wire")
    assert (report.indexed, report.skipped, report.stopped) == (2, 0, None)

    async with sessions() as session:
        posts = (
            (
                await session.execute(
                    select(TelegramPost)
                    .where(TelegramPost.channel == "demo_wire")
                    .order_by(TelegramPost.message_id)
                )
            )
            .scalars()
            .all()
        )
        row = (
            await session.execute(
                select(TelegramChannel).where(TelegramChannel.channel == "demo_wire")
            )
        ).scalar_one()
    assert [p.message_id for p in posts] == [10, 11]
    assert posts[0].forwarded_from_channel == "first_hand"
    assert posts[0].forwarded_from_message_id == 7
    assert posts[0].collected_via == "preview"
    assert len(posts[0].phash) == 16 and len(posts[0].embedding) == 512
    assert row.newest_collected_id == 11

    again = await collector.collect(source, "demo_wire", resume=False)
    assert (again.indexed, again.skipped) == (0, 2)


@pytest.mark.db
async def test_collector_refuses_channels_off_the_watchlist(
    db_engine: AsyncEngine, tmp_path: Path
) -> None:
    collector = Collector(
        sessions=make_sessionmaker(db_engine),
        blobs=FilesystemBlobStore(tmp_path),
        embedder=FakeEmbedder(),
        max_pixels=50_000_000,
    )
    source = PreviewSource(_fetcher(_web(), []), _pacer(FakeClock()))
    report = await collector.collect(source, "not_listed")
    assert report.stopped == "not on the watchlist" and report.indexed == 0


def test_channel_photo_is_plain_data() -> None:
    photo = ChannelPhoto(
        channel="demo_wire",
        message_id=1,
        photo_index=0,
        posted_at=datetime(2024, 1, 1, tzinfo=UTC),
        text="",
        forwarded_from=None,
        image_url="https://cdn.telesco.pe/x.jpg",
        data=b"",
        content_type="image/jpeg",
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert photo.http_headers is None
