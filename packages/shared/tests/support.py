"""Test doubles and helpers shared by the provider tests."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.enums import QuotaPeriod
from origin_core.providers import quota
from origin_core.providers.base import AssetRef, CandidateHit, ProviderError, RawResponse

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


def json_body(*pages: str) -> RawResponse:
    items = [{"page": p, "image": f"{p}/img.jpg"} for p in pages]
    return RawResponse(json.dumps(items).encode())


ASSET = AssetRef(
    id="asset", sha256="d" * 64, content_type="image/jpeg", data=b"jpeg", width=1, height=1
)


async def no_sleep(_: float) -> None:
    return None


def make_policy(limit: int, *, charges_failed: bool = False) -> quota.QuotaPolicy:
    return quota.QuotaPolicy(
        f"q-{uuid.uuid4().hex[:8]}", {QuotaPeriod.MONTH: limit}, charges_failed
    )


async def used_units(sessions: async_sessionmaker[AsyncSession], policy: quota.QuotaPolicy) -> int:
    async with sessions() as session:
        return (await quota.remaining(session, policy, NOW))[0].used
