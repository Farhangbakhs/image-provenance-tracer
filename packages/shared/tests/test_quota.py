from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from origin_core.db.session import make_sessionmaker
from origin_core.enums import QuotaPeriod
from origin_core.providers import quota

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 10, 14, 37, tzinfo=UTC)


def _policy(
    month: int = 5, hour: int | None = None, *, charges_failed: bool = False
) -> quota.QuotaPolicy:
    limits = {QuotaPeriod.MONTH: month}
    if hour is not None:
        limits[QuotaPeriod.HOUR] = hour
    return quota.QuotaPolicy(f"test-{uuid.uuid4().hex[:8]}", limits, charges_failed)


def test_period_start_aligns_to_utc() -> None:
    assert quota.period_start(QuotaPeriod.HOUR, NOW) == datetime(2026, 11, 10, 14, tzinfo=UTC)
    assert quota.period_start(QuotaPeriod.MONTH, NOW) == datetime(2026, 11, 1, tzinfo=UTC)


async def test_debit_until_exhausted(db_engine: AsyncEngine) -> None:
    sessions = make_sessionmaker(db_engine)
    policy = _policy(month=3)
    for _ in range(3):
        async with sessions.begin() as session:
            await quota.debit(session, policy, 1, NOW)
    with pytest.raises(quota.QuotaExhausted):
        async with sessions.begin() as session:
            await quota.debit(session, policy, 1, NOW)
    async with sessions() as session:
        [month] = await quota.remaining(session, policy, NOW)
    assert (month.used, month.remaining) == (3, 0)


async def test_every_period_must_have_room(db_engine: AsyncEngine) -> None:
    sessions = make_sessionmaker(db_engine)
    policy = _policy(month=10, hour=2)
    for _ in range(2):
        async with sessions.begin() as session:
            await quota.debit(session, policy, 1, NOW)
    with pytest.raises(quota.QuotaExhausted) as excinfo:
        async with sessions.begin() as session:
            await quota.debit(session, policy, 1, NOW)
    assert excinfo.value.period is QuotaPeriod.HOUR
    # The failed debit reserved nothing in the month either.
    async with sessions() as session:
        by_period = {r.period: r.used for r in await quota.remaining(session, policy, NOW)}
    assert by_period == {QuotaPeriod.MONTH: 2, QuotaPeriod.HOUR: 2}
    # The next hour has room again.
    async with sessions.begin() as session:
        await quota.debit(session, policy, 1, NOW.replace(hour=15))


async def test_refund_returns_units(db_engine: AsyncEngine) -> None:
    sessions = make_sessionmaker(db_engine)
    policy = _policy(month=2)
    async with sessions.begin() as session:
        await quota.debit(session, policy, 2, NOW)
    async with sessions.begin() as session:
        await quota.refund(session, policy, 1, NOW)
    async with sessions() as session:
        [month] = await quota.remaining(session, policy, NOW)
    assert month.used == 1


async def test_concurrent_debits_never_overspend(db_engine: AsyncEngine) -> None:
    sessions = make_sessionmaker(db_engine)
    policy = _policy(month=5)

    async def attempt() -> bool:
        try:
            async with sessions.begin() as session:
                await quota.debit(session, policy, 1, NOW)
        except quota.QuotaExhausted:
            return False
        return True

    results = await asyncio.gather(*(attempt() for _ in range(12)))
    assert sum(results) == 5
    async with sessions() as session:
        [month] = await quota.remaining(session, policy, NOW)
    assert month.used == 5
