"""A full trace through the real stages (ingest, discover, verify, date) against a simulated web.

The provider is a scripted test double, and pages, images and the Wayback CDX API are served
from an in-memory transport. Everything else is real: the hardened fetcher, page parsing,
fingerprints, SSCD, homography matching, the dating rule, Postgres and the blob store.
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from testkit import SeedRun

from origin_core.db.models import Candidate, Sighting, TimestampEvidence
from origin_core.db.session import make_sessionmaker
from origin_core.enums import CandidateStatus, DateConfidence, EvidenceKind, MatchClass, RunStatus
from origin_core.fetch import Fetcher
from origin_core.pipeline.events import RunEventBus
from origin_core.pipeline.runner import PipelineRunner
from origin_core.providers import wayback
from origin_core.providers.base import AssetRef, CandidateHit, RawResponse
from origin_core.providers.registry import ProviderSetup
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.storage import FilesystemBlobStore
from origin_worker.embedding import SSCDEmbedder
from origin_worker.matching.thresholds import load_thresholds
from origin_worker.stages import TraceServices, build_stages

pytestmark = [pytest.mark.db, pytest.mark.redis]

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "c2pa"
PUBLIC_IP = "93.184.216.34"


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


class ScriptedProvider:
    """Test double standing in for a reverse-image engine."""

    name: str = "scripted"
    quota_key: str = "scripted"
    unit_cost: int = 0
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("nobody (test)",)

    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._body = json.dumps(hits).encode()

    def params(self) -> dict[str, Any]:
        return {}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        return RawResponse(self._body)

    def parse(self, body: bytes) -> list[CandidateHit]:
        return [CandidateHit(**hit) for hit in json.loads(body)]


def _web(photo: Image.Image) -> dict[tuple[str, str], httpx.Response]:
    w, h = photo.size
    derivative = photo.crop((int(w * 0.1), int(h * 0.05), int(w * 0.9), int(h * 0.85)))
    ImageDraw.Draw(derivative).rectangle(
        (0, int(derivative.height * 0.8), derivative.width, derivative.height), fill=(0, 0, 0)
    )
    page = b"""<html><head><title>Floods</title>
    <meta property="og:image" content="https://news.example/media/flood.jpg">
    <meta property="article:published_time" content="2024-03-05T09:00:00Z">
    </head><body><img src="/static/logo.png" width="20" height="20"></body></html>"""
    return {
        ("news.example", "/story"): httpx.Response(
            200, headers={"content-type": "text/html"}, content=page
        ),
        ("news.example", "/media/flood.jpg"): httpx.Response(
            200, headers={"content-type": "image/jpeg"}, content=_jpeg(derivative)
        ),
        ("cdn.example", "/copy.jpg"): httpx.Response(
            200,
            headers={
                "content-type": "image/jpeg",
                "last-modified": "Tue, 12 Mar 2024 08:00:00 GMT",
            },
            content=_jpeg(photo.resize((w // 2, h // 2))),
        ),
        ("other.example", "/x.jpg"): httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=(FIXTURES / "signed-test-cert.jpg").read_bytes(),
        ),
        ("gone.example", "/"): httpx.Response(404),
    }


def _wayback(request: httpx.Request) -> httpx.Response:
    url = request.url.params.get("url", "")
    if url == "https://news.example/story":
        rows = [
            ["timestamp", "original", "statuscode", "mimetype", "digest"],
            ["20240306120000", url, "200", "text/html", "D"],
        ]
        return httpx.Response(200, json=rows)
    return httpx.Response(200, json=[])


async def test_full_trace_produces_verified_dated_sightings(
    db_engine: AsyncEngine,
    redis: Redis,
    tmp_path: Path,
    embedder: SSCDEmbedder,
    seed_run: SeedRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wayback, "_PACER", wayback._Pacer(0))  # pyright: ignore[reportPrivateUsage]
    photo_bytes = (FIXTURES / "no-manifest.jpg").read_bytes()
    with Image.open(io.BytesIO(photo_bytes)) as opened:
        photo = opened.convert("RGB")
    web = _web(photo)

    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC_IP]

    def serve(request: httpx.Request) -> httpx.Response:
        return web.get((request.headers["host"], request.url.path), httpx.Response(404))

    blobs = FilesystemBlobStore(tmp_path)
    sessions = make_sessionmaker(db_engine)
    provider = ScriptedProvider(
        [
            {"page_url": "https://news.example/story", "rank": 1, "provider_date": None},
            {"image_url": "https://cdn.example/copy.jpg", "rank": 2},
            {"image_url": "https://other.example/x.jpg", "rank": 3},
            {"page_url": "https://gone.example/", "rank": 4},
        ]
    )
    runner = ProviderRunner(
        sessions=sessions,
        blobs=blobs,
        http=httpx.AsyncClient(transport=httpx.MockTransport(_wayback)),
        policies={},
        retry=RetryPolicy(attempts=1),
    )
    fetcher = Fetcher(resolver=resolve, transport=httpx.MockTransport(serve))
    stages = build_stages(
        blobs=blobs,
        embedder=embedder,
        trace=TraceServices(
            providers=ProviderSetup(
                adapters=[provider], unavailable={"lens": "SERPAPI_API_KEY is not set"}
            ),
            runner=runner,
            fetcher=fetcher,
            thresholds=load_thresholds(),
            max_pixels=50_000_000,
            exiftool="exiftool",
        ),
    )
    run_id = await seed_run(image=photo_bytes, blobs=blobs)

    status = await PipelineRunner(
        sessions=sessions, events=RunEventBus(redis), stages=stages
    ).execute(run_id)
    assert status is RunStatus.SUCCEEDED

    async with sessions() as session:
        candidates = {
            c.page_url or c.image_url: c
            for c in (
                await session.execute(select(Candidate).where(Candidate.run_id == run_id))
            ).scalars()
        }
        sightings = {
            s.page_url or s.image_url: s
            for s in (
                await session.execute(select(Sighting).where(Sighting.run_id == run_id))
            ).scalars()
        }
        evidence: dict[object, dict[EvidenceKind, TimestampEvidence]] = {}
        for sighting in sightings.values():
            rows = (
                await session.execute(
                    select(TimestampEvidence).where(TimestampEvidence.sighting_id == sighting.id)
                )
            ).scalars()
            evidence[sighting.id] = {row.kind: row for row in rows}

    # Candidates are judged, not trusted.
    assert candidates["https://news.example/story"].status is CandidateStatus.VERIFIED
    assert candidates["https://cdn.example/copy.jpg"].status is CandidateStatus.VERIFIED
    assert candidates["https://other.example/x.jpg"].status is CandidateStatus.UNRELATED
    assert candidates["https://gone.example/"].status is CandidateStatus.FETCH_FAILED
    assert set(sightings) == {"https://news.example/story", "https://cdn.example/copy.jpg"}

    # The news page's image was found on the page and identified as a cropped, captioned copy.
    news = sightings["https://news.example/story"]
    assert news.image_url == "https://news.example/media/flood.jpg"
    assert news.match_class is MatchClass.DERIVATIVE
    assert news.transform is not None and {"crop", "overlay"} <= set(news.transform["edits"])
    assert news.threshold_version == "match.v2"
    # Dated between the page's own claim and the archive's proof, at medium confidence.
    assert news.date_lower == datetime(2024, 3, 5, 9, tzinfo=UTC)
    assert news.date_upper == datetime(2024, 3, 6, 12, tzinfo=UTC)
    assert news.date_confidence is DateConfidence.MEDIUM
    news_evidence = evidence[news.id]
    assert {EvidenceKind.OBSERVED, EvidenceKind.WAYBACK_PAGE, EvidenceKind.PAGE_METADATA} <= set(
        news_evidence
    )
    assert news.deciding_evidence_id == news_evidence[EvidenceKind.PAGE_METADATA].id

    # The CDN copy is the same picture resized; its Last-Modified header is a weak claim.
    cdn = sightings["https://cdn.example/copy.jpg"]
    assert cdn.match_class is MatchClass.NEAR_DUPLICATE
    assert cdn.date_lower == datetime(2024, 3, 12, 8, tzinfo=UTC)
    assert cdn.date_confidence is DateConfidence.LOW
    assert EvidenceKind.HTTP_LAST_MODIFIED in evidence[cdn.id]

    await fetcher.aclose()
