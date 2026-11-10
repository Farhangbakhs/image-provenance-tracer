"""Wayback first captures: contract tests against real recorded CDX responses, replayed offline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from origin_core.db.session import make_sessionmaker
from origin_core.enums import ProviderCallStatus
from origin_core.providers.base import ProviderError, UrlSubject
from origin_core.providers.fixtures import FixtureStore
from origin_core.providers.runner import ProviderRunner
from origin_core.providers.wayback import (
    WaybackFirstCapture,
    archive_url,
    first_capture,
    parse_cdx_timestamp,
)
from origin_core.settings import ProviderMode
from origin_core.storage import FilesystemBlobStore

RECORDINGS = Path(__file__).resolve().parents[3] / "fixtures" / "recordings"


def test_parses_cdx_rows() -> None:
    body = (
        b'[["timestamp","original","statuscode","mimetype","digest"],'
        b'["20020120142510","http://example.com:80/","200","text/html","HT2D"]]'
    )
    capture = first_capture(WaybackFirstCapture().parse(body))
    assert capture is not None
    assert capture.captured_at == datetime(2002, 1, 20, 14, 25, 10, tzinfo=UTC)
    assert (
        capture.archive_url
        == "https://web.archive.org/web/20020120142510id_/http://example.com:80/"
    )
    assert capture.mimetype == "text/html"


@pytest.mark.parametrize("body", [b"[]", b"[]\n", b""])
def test_never_archived_is_none(body: bytes) -> None:
    assert first_capture(WaybackFirstCapture().parse(body)) is None


def test_helpers() -> None:
    assert parse_cdx_timestamp("19991231235959") == datetime(1999, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert (
        archive_url("2020", "https://a.example/x.jpg")
        == "https://web.archive.org/web/2020id_/https://a.example/x.jpg"
    )


async def test_rate_limits_and_server_errors_are_retryable() -> None:
    async def busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(busy)) as client:
        with pytest.raises(ProviderError) as exc:
            await WaybackFirstCapture().fetch(UrlSubject("example.com/"), client)
    assert exc.value.retryable


@pytest.mark.db
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("example.com/", datetime(2002, 1, 20, 14, 25, 10, tzinfo=UTC)),
        ("this-domain-should-not-exist-origin-test.example/", None),
    ],
)
async def test_replays_real_recordings_offline(
    db_engine: AsyncEngine, tmp_path: Path, url: str, expected: datetime | None
) -> None:
    runner = ProviderRunner(
        sessions=make_sessionmaker(db_engine),
        blobs=FilesystemBlobStore(tmp_path),
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(599))),
        policies={},
        mode=ProviderMode.REPLAY,
        fixtures=FixtureStore((RECORDINGS,)),
    )
    outcome = await runner.run(WaybackFirstCapture(), UrlSubject(url))
    assert outcome.status is ProviderCallStatus.REPLAYED
    capture = first_capture(outcome.hits)
    assert (capture.captured_at if capture else None) == expected
