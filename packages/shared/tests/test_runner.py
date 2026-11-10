"""ProviderRunner behaviour: caching, quota, retries, breaker and recording."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from origin_core.db.models import Artefact, ProviderCall
from origin_core.db.session import make_sessionmaker
from origin_core.enums import ProviderCallStatus, QuotaPeriod
from origin_core.providers import quota
from origin_core.providers.base import AssetRef, CandidateHit, ProviderError, RawResponse
from origin_core.providers.breaker import BreakerRegistry, CircuitBreaker
from origin_core.providers.runner import ProviderRunner, RetryPolicy
from origin_core.storage import FilesystemBlobStore

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


class ScriptedAdapter:
    """Test double: returns or raises the scripted results in order, and counts calls."""

    unit_cost: int = 1
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("nobody (test)",)

    def __init__(self, script: list[RawResponse | ProviderError], *, quota_key: str) -> None:
        self.name: str = f"scripted-{uuid.uuid4().hex[:8]}"
        self.quota_key: str = quota_key
        self._script = list(script)
        self.calls = 0

    def params(self) -> dict[str, Any]:
        return {"type": "exact"}

    async def fetch(self, asset: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        self.calls += 1
        step = self._script.pop(0)
        if isinstance(step, ProviderError):
            raise step
        return step

    def parse(self, body: bytes) -> list[CandidateHit]:
        data = json.loads(body)
        return [CandidateHit(page_url=item["page"], image_url=item["image"]) for item in data]


def _body(*pages: str) -> RawResponse:
    items = [{"page": p, "image": f"{p}/img.jpg"} for p in pages]
    return RawResponse(json.dumps(items).encode())


ASSET = AssetRef(
    id="asset", sha256="d" * 64, content_type="image/jpeg", data=b"jpeg", width=1, height=1
)


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
async def sessions(db_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield make_sessionmaker(db_engine)


def _runner(
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    policies: dict[str, quota.QuotaPolicy],
    *,
    breakers: BreakerRegistry | None = None,
) -> ProviderRunner:
    return ProviderRunner(
        sessions=sessions,
        blobs=FilesystemBlobStore(tmp_path),
        http=httpx.AsyncClient(),
        policies=policies,
        breakers=breakers,
        retry=RetryPolicy(attempts=3, timeout_s=5),
        clock=lambda: NOW,
        sleep=_no_sleep,
    )


def _policy(limit: int, *, charges_failed: bool = False) -> quota.QuotaPolicy:
    return quota.QuotaPolicy(
        f"q-{uuid.uuid4().hex[:8]}", {QuotaPeriod.MONTH: limit}, charges_failed
    )


async def _used(sessions: async_sessionmaker[AsyncSession], policy: quota.QuotaPolicy) -> int:
    async with sessions() as session:
        return (await quota.remaining(session, policy, NOW))[0].used


async def test_success_records_call_artefact_and_quota(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(5)
    adapter = ScriptedAdapter([_body("https://a.example")], quota_key=policy.key)
    outcome = await _runner(sessions, tmp_path, {policy.key: policy}).run(adapter, ASSET)

    assert outcome.status is ProviderCallStatus.OK
    assert [h.page_url for h in outcome.hits] == ["https://a.example"]
    assert await _used(sessions, policy) == 1
    async with sessions() as session:
        call = await session.get_one(ProviderCall, outcome.call_id)
        artefact = await session.get_one(Artefact, call.raw_artefact_id)
    assert call.units == 1
    assert artefact.byte_size > 0
    assert (tmp_path / artefact.storage_key).exists()


async def test_repeat_query_is_served_from_cache_without_quota(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(5)
    adapter = ScriptedAdapter([_body("https://a.example")], quota_key=policy.key)
    runner = _runner(sessions, tmp_path, {policy.key: policy})
    first = await runner.run(adapter, ASSET)
    second = await runner.run(adapter, ASSET)

    assert second.status is ProviderCallStatus.CACHED
    assert second.hits == first.hits
    assert adapter.calls == 1
    assert await _used(sessions, policy) == 1


async def test_exhausted_quota_skips_without_calling(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(0)
    adapter = ScriptedAdapter([_body("https://a.example")], quota_key=policy.key)
    outcome = await _runner(sessions, tmp_path, {policy.key: policy}).run(adapter, ASSET)

    assert outcome.status is ProviderCallStatus.SKIPPED_QUOTA
    assert adapter.calls == 0
    assert not outcome.usable


async def test_retryable_errors_are_retried(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(5)
    adapter = ScriptedAdapter(
        [ProviderError("503", retryable=True), _body("https://a.example")], quota_key=policy.key
    )
    outcome = await _runner(sessions, tmp_path, {policy.key: policy}).run(adapter, ASSET)

    assert outcome.status is ProviderCallStatus.OK
    assert adapter.calls == 2
    assert await _used(sessions, policy) == 1


async def test_failure_is_recorded_and_unbilled_units_refunded(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(5, charges_failed=False)
    adapter = ScriptedAdapter([ProviderError("bad key", retryable=False)], quota_key=policy.key)
    outcome = await _runner(sessions, tmp_path, {policy.key: policy}).run(adapter, ASSET)

    assert outcome.status is ProviderCallStatus.ERROR
    assert outcome.error == "bad key"
    assert adapter.calls == 1
    assert await _used(sessions, policy) == 0
    async with sessions() as session:
        call = await session.get_one(ProviderCall, outcome.call_id)
    assert call.error == "bad key"


async def test_billed_failures_keep_their_units(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(5, charges_failed=True)
    adapter = ScriptedAdapter([ProviderError("400", retryable=False)], quota_key=policy.key)
    await _runner(sessions, tmp_path, {policy.key: policy}).run(adapter, ASSET)
    assert await _used(sessions, policy) == 1


async def test_open_breaker_skips_provider(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    policy = _policy(10)
    breakers = BreakerRegistry(lambda: CircuitBreaker(threshold=1, cooldown_s=3600))
    adapter = ScriptedAdapter([ProviderError("down", retryable=False)], quota_key=policy.key)
    runner = _runner(sessions, tmp_path, {policy.key: policy}, breakers=breakers)
    await runner.run(adapter, ASSET)
    outcome = await runner.run(adapter, ASSET)

    assert outcome.status is ProviderCallStatus.SKIPPED_BREAKER
    assert adapter.calls == 1


async def test_unparseable_response_is_kept_and_reported(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    adapter = ScriptedAdapter([RawResponse(b"<html>not json</html>")], quota_key="unmetered")
    outcome = await _runner(sessions, tmp_path, {}).run(adapter, ASSET)

    assert outcome.status is ProviderCallStatus.ERROR
    assert outcome.error is not None and outcome.error.startswith("parse error")
    async with sessions() as session:
        call = (
            await session.execute(select(ProviderCall).where(ProviderCall.id == outcome.call_id))
        ).scalar_one()
    assert call.raw_artefact_id is not None  # the raw body is still stored for inspection
