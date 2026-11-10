"""Quota metering for free-tier providers.

Units are debited *before* a call, under a row lock, so concurrent workers can never overspend
a free tier. Each quota bucket may have several periods (SerpApi: 250 a month and 50 an hour);
a debit succeeds only if every period has room.

Limits are deliberately set a little under the vendors' published allowances where an
overrun would be billed (Cloud Vision), and periods are aligned to UTC calendar boundaries,
which may differ from a vendor's billing anniversary. See PLAN.md section 1.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from origin_core.db.models import ProviderQuota
from origin_core.enums import QuotaPeriod


@dataclass(frozen=True)
class QuotaPolicy:
    key: str
    limits: dict[QuotaPeriod, int]
    #: Whether the vendor bills calls that fail. SerpApi counts only successful searches.
    charges_failed_calls: bool


DEFAULT_POLICIES: dict[str, QuotaPolicy] = {
    # Cloud Vision: 1,000 free units a month, then billed. Hard stop at 950 so a miscount
    # cannot reach a charge.
    "vision": QuotaPolicy("vision", {QuotaPeriod.MONTH: 950}, charges_failed_calls=True),
    # SerpApi free plan: 250 searches a month, 50 an hour; only successful searches count.
    "serpapi": QuotaPolicy(
        "serpapi", {QuotaPeriod.MONTH: 250, QuotaPeriod.HOUR: 50}, charges_failed_calls=False
    ),
}


class QuotaExhausted(Exception):
    def __init__(self, key: str, period: QuotaPeriod, used: int, limit: int) -> None:
        super().__init__(f"quota '{key}' exhausted for {period.value}: {used}/{limit} used")
        self.key = key
        self.period = period


@dataclass(frozen=True)
class QuotaRemaining:
    period: QuotaPeriod
    period_start: datetime
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return self.limit - self.used


def period_start(period: QuotaPeriod, now: datetime) -> datetime:
    now = now.astimezone(UTC)
    if period is QuotaPeriod.HOUR:
        return now.replace(minute=0, second=0, microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _locked_rows(
    session: AsyncSession, policy: QuotaPolicy, now: datetime
) -> list[ProviderQuota]:
    rows: list[ProviderQuota] = []
    for period, limit in sorted(policy.limits.items()):  # fixed lock order avoids deadlocks
        start = period_start(period, now)
        await session.execute(
            insert(ProviderQuota)
            .values(
                provider=policy.key,
                period_kind=period,
                period_start=start,
                limit_units=limit,
                used_units=0,
            )
            .on_conflict_do_nothing(index_elements=["provider", "period_kind", "period_start"])
        )
        row = (
            await session.execute(
                select(ProviderQuota)
                .where(
                    ProviderQuota.provider == policy.key,
                    ProviderQuota.period_kind == period,
                    ProviderQuota.period_start == start,
                )
                .with_for_update()
            )
        ).scalar_one()
        rows.append(row)
    return rows


async def debit(session: AsyncSession, policy: QuotaPolicy, units: int, now: datetime) -> None:
    """Reserve `units` in every period, or raise QuotaExhausted and reserve nothing.

    The caller owns the transaction: commit to keep the debit, roll back to drop it.
    """
    if units < 0:
        raise ValueError("units must be non-negative")
    rows = await _locked_rows(session, policy, now)
    for row in rows:
        if row.used_units + units > row.limit_units:
            raise QuotaExhausted(policy.key, row.period_kind, row.used_units, row.limit_units)
    for row in rows:
        row.used_units += units
    await session.flush()


async def refund(session: AsyncSession, policy: QuotaPolicy, units: int, now: datetime) -> None:
    """Return units for a call the vendor does not bill (e.g. a failed SerpApi search)."""
    for row in await _locked_rows(session, policy, now):
        row.used_units = max(0, row.used_units - units)
    await session.flush()


async def remaining(
    session: AsyncSession, policy: QuotaPolicy, now: datetime
) -> list[QuotaRemaining]:
    result: list[QuotaRemaining] = []
    for period, limit in sorted(policy.limits.items()):
        start = period_start(period, now)
        used = (
            await session.execute(
                select(ProviderQuota.used_units).where(
                    ProviderQuota.provider == policy.key,
                    ProviderQuota.period_kind == period,
                    ProviderQuota.period_start == start,
                )
            )
        ).scalar_one_or_none()
        result.append(QuotaRemaining(period, start, used or 0, limit))
    return result
