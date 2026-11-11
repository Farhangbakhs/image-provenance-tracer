"""Phase 5 end to end: the targeted sweep finds a Telegram post earlier than any web sighting.

SYNTHETIC: the web page, the channel's t.me/s preview, the post page and the photo CDN are
served from an in-memory transport, in the markup checked against live pages (see
origin_core.telegram.preview). Everything else is real: the collector, the SSCD index query,
the hardened fetcher, matching, the dating rule, Postgres and the blob store.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import ScriptedProvider, SeedRun

from origin_core.db.models import Candidate, Run, Sighting, TelegramPost, TimestampEvidence
from origin_core.db.session import make_sessionmaker
from origin_core.enums import BoundType, CandidateStatus, EvidenceKind, RunStatus
from origin_core.fetch import Fetcher
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import PipelineRunner
from origin_core.providers import wayback
from origin_core.providers.registry import ProviderSetup
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.providers.telegram import TelegramIndex
from origin_core.storage import FilesystemBlobStore
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.stages import TelegramServices, TraceServices, build_stages
from origin_worker.telegram.collector import Collector, SSCDModel, add_channel
from origin_worker.telegram.sources import Pacer, PreviewSource

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"
PUBLIC_IP = "93.184.216.34"


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue()


def _post(channel: str, number: int, when: str) -> str:
    return (
        f'<div class="tgme_widget_message js-widget_message" data-post="{channel}/{number}">'
        f'<a class="tgme_widget_message_photo_wrap" href="https://t.me/{channel}/{number}" '
        f"style=\"background-image:url('https://cdn.telesco.pe/{channel}/{number}.jpg')\"></a>"
        f'<div class="tgme_widget_message_text">Floods in the valley, post {number}</div>'
        f'<a class="tgme_widget_message_date" href="https://t.me/{channel}/{number}">'
        f'<time datetime="{when}">t</time></a></div>'
    )


def _web(photo: Image.Image, channel: str) -> dict[tuple[str, str], httpx.Response]:
    w, h = photo.size
    html = {"content-type": "text/html"}
    jpeg = {"content-type": "image/jpeg"}
    unrelated = (FIXTURES / "signed-test-cert.jpg").read_bytes()
    preview = (
        "<html><body>"
        + _post(channel, 39, "2024-01-01T08:00:00+00:00")  # outside the sweep window
        + _post(channel, 40, "2024-03-01T10:00:00+00:00")  # the same picture, earlier
        + _post(channel, 41, "2024-03-04T12:00:00+00:00")  # a different picture
        + "</body></html>"
    ).encode()
    web = {
        ("valley-news.example", "/story"): httpx.Response(
            200,
            headers=html,
            content=b"""<html><head><title>Floods in the valley</title>
            <meta property="og:image" content="https://valley-news.example/flood.jpg">
            <meta property="article:published_time" content="2024-03-05T09:00:00Z">
            </head><body></body></html>""",
        ),
        ("valley-news.example", "/flood.jpg"): httpx.Response(
            200, headers=jpeg, content=_jpeg(photo)
        ),
        ("t.me", f"/s/{channel}"): httpx.Response(200, headers=html, content=preview),
    }
    photos = {39: _jpeg(photo), 40: _jpeg(photo.resize((w * 3 // 4, h * 3 // 4))), 41: unrelated}
    for number, data in photos.items():
        web[("cdn.telesco.pe", f"/{channel}/{number}.jpg")] = httpx.Response(
            200, headers=jpeg, content=data
        )
        web[("t.me", f"/{channel}/{number}")] = httpx.Response(
            200,
            headers=html,
            content=(
                f'<html><head><meta property="og:image" '
                f'content="https://cdn.telesco.pe/{channel}/{number}.jpg"></head></html>'
            ).encode(),
        )
    return web


def _wayback(request: httpx.Request) -> httpx.Response:
    url = request.url.params.get("url", "")
    if url == "https://valley-news.example/story":
        rows = [
            ["timestamp", "original", "statuscode", "mimetype", "digest"],
            ["20240306120000", url, "200", "text/html", "D"],
        ]
        return httpx.Response(200, json=rows)
    return httpx.Response(200, json=[])


async def test_sweep_surfaces_a_telegram_post_earlier_than_the_web(
    db_engine: AsyncEngine,
    redis: Redis,
    tmp_path: Path,
    embedder: SSCDEmbedder,
    seed_run: SeedRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wayback, "_PACER", wayback._Pacer(0))  # pyright: ignore[reportPrivateUsage]
    channel = f"wire_{uuid.uuid4().hex[:10]}"
    photo_bytes = (FIXTURES / "no-manifest.jpg").read_bytes()
    with Image.open(io.BytesIO(photo_bytes)) as opened:
        photo = opened.convert("RGB")
    web = _web(photo, channel)
    requested: list[str] = []

    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC_IP]

    def serve(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url.copy_with(host=request.headers["host"])))
        return web.get((request.headers["host"], request.url.path), httpx.Response(404))

    blobs = FilesystemBlobStore(tmp_path)
    sessions = make_sessionmaker(db_engine)
    await add_channel(sessions, channel, added_by="test", note="synthetic")
    fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))
    index = TelegramIndex(sessions)
    stages = build_stages(
        blobs=blobs,
        embedder=embedder,
        trace=TraceServices(
            providers=ProviderSetup(
                adapters=[
                    ScriptedProvider(
                        [{"page_url": "https://valley-news.example/story", "rank": 1}],
                        name=f"scripted-{channel}",
                    ),
                    index,
                ]
            ),
            runner=ProviderRunner(
                sessions=sessions,
                blobs=blobs,
                http=httpx.AsyncClient(transport=httpx.MockTransport(_wayback)),
                policies={},
                retry=RetryPolicy(attempts=1),
            ),
            fetcher=fetcher,
            thresholds=load_thresholds(),
            max_pixels=50_000_000,
            exiftool="exiftool",
            telegram=TelegramServices(
                collector=Collector(
                    sessions=sessions,
                    blobs=blobs,
                    embedder=SSCDModel(embedder),
                    max_pixels=50_000_000,
                ),
                source=PreviewSource(fetcher, Pacer(0.0)),
            ),
        ),
    )
    assert [s.name for s in stages][:6] == [
        "ingest",
        "discover",
        "verify",
        "date",
        "telegram_sweep",
        "branch",
    ]
    run_id = await seed_run(image=photo_bytes, blobs=blobs)
    status = await PipelineRunner(
        sessions=sessions, events=RunEventBus(redis), stages=stages
    ).execute(run_id)
    assert status is RunStatus.SUCCEEDED

    async with sessions() as session:
        run = await session.get_one(Run, run_id)
        rows = (
            await session.execute(
                select(Sighting, Candidate)
                .join(Candidate, Candidate.id == Sighting.candidate_id)
                .where(Sighting.run_id == run_id)
            )
        ).all()
        indexed = (
            (await session.execute(select(TelegramPost).where(TelegramPost.channel == channel)))
            .scalars()
            .all()
        )
        unrelated = (
            await session.execute(
                select(Candidate).where(
                    Candidate.run_id == run_id,
                    Candidate.page_url == f"https://t.me/{channel}/41",
                )
            )
        ).scalar_one_or_none()
        by_url = {s.page_url: (s, c) for s, c in rows}
        tg, tg_candidate = by_url[f"https://t.me/{channel}/40"]
        platform = (
            await session.execute(
                select(TimestampEvidence).where(
                    TimestampEvidence.sighting_id == tg.id,
                    TimestampEvidence.kind == EvidenceKind.PLATFORM,
                )
            )
        ).scalar_one()

    # The sweep searched the channel for the page's keywords, inside the window only.
    sweep = run.stages["telegram_sweep"]
    assert sweep["counts"]["indexed"] == 2
    assert "floods, valley" in sweep["notes"]["sweep"]
    assert sorted(p.message_id for p in indexed) == [40, 41]
    assert any(f"t.me/s/{channel}?q=floods" in url for url in requested)

    # The Telegram post was verified like any web page and dated by its platform time.
    assert tg_candidate.provider == "telegram" and tg_candidate.raw["sweep"] is True
    assert tg_candidate.status is CandidateStatus.VERIFIED
    assert platform.bound is BoundType.EXACT
    assert platform.value == datetime(2024, 3, 1, 10, tzinfo=UTC)
    assert tg.date_upper == datetime(2024, 3, 1, 10, tzinfo=UTC)

    # It is earlier than every web sighting.
    earliest_telegram = tg.date_upper
    assert earliest_telegram is not None
    web_dates: list[datetime] = []
    for sighting, candidate in rows:
        if candidate.provider != "telegram":
            when = sighting.date_lower or sighting.date_upper
            assert when is not None
            web_dates.append(when)
    assert web_dates and all(earliest_telegram < d for d in web_dates)
    # The different picture on the same channel never became a sighting.
    assert unrelated is None or unrelated.status is not CandidateStatus.VERIFIED

    await fetcher.aclose()
