"""ProviderRunner: the one path every provider call takes.

For each (adapter, image) it:

1. derives a request hash from the provider name, the image's SHA-256 and the parameters;
2. serves a stored response for that hash if one exists (no quota spent);
3. skips the provider if its circuit breaker is open;
4. reserves quota under a row lock, or skips the provider if the free tier is spent;
5. calls the adapter with a timeout and retries retryable failures with jittered backoff;
6. stores the raw response as an artefact and records a `provider_calls` row, whatever
   the outcome, so every query is auditable and replayable.

In record mode it also writes each response (secrets redacted) to the fixture tree. In replay
mode it never touches the network, the cache or the quota: it serves recordings only, and a
query without a recording fails loudly instead of silently returning nothing.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.artefacts import store_artefact
from origin_core.db.models import Artefact, ProviderCall
from origin_core.enums import ArtefactKind, ProviderCallStatus
from origin_core.hashing import request_hash
from origin_core.providers import quota
from origin_core.providers.base import (
    AssetRef,
    CandidateHit,
    ProviderAdapter,
    ProviderError,
    RawResponse,
)
from origin_core.providers.breaker import BreakerRegistry
from origin_core.providers.fixtures import FixtureStore
from origin_core.settings import ProviderMode
from origin_core.storage import BlobStore

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    timeout_s: float = 30.0

    def delay(self, attempt: int) -> float:
        """Full-jitter exponential backoff for the given (1-based) failed attempt."""
        ceiling = min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1))
        return random.uniform(0, ceiling)  # noqa: S311  (jitter, not security)


@dataclass(frozen=True)
class ProviderOutcome:
    provider: str
    status: ProviderCallStatus
    call_id: uuid.UUID
    request_hash: str
    hits: list[CandidateHit]
    units: int
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.status in {
            ProviderCallStatus.OK,
            ProviderCallStatus.CACHED,
            ProviderCallStatus.REPLAYED,
        }


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProviderRunner:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        http: httpx.AsyncClient,
        policies: dict[str, quota.QuotaPolicy],
        breakers: BreakerRegistry | None = None,
        retry: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        mode: ProviderMode = ProviderMode.LIVE,
        fixtures: FixtureStore | None = None,
        redact_secrets: tuple[str, ...] = (),
    ) -> None:
        if mode is not ProviderMode.LIVE and fixtures is None:
            raise ValueError(f"provider mode '{mode.value}' needs a FixtureStore")
        self._sessions = sessions
        self._blobs = blobs
        self._http = http
        self._policies = policies
        self._breakers = breakers or BreakerRegistry()
        self._retry = retry or RetryPolicy()
        self._clock = clock
        self._sleep = sleep
        self._mode = mode
        self._fixtures = fixtures
        self._redact = redact_secrets

    async def run(
        self, adapter: ProviderAdapter, asset: AssetRef, *, run_id: uuid.UUID | None = None
    ) -> ProviderOutcome:
        params = adapter.params()
        rh = request_hash(adapter.name, asset.sha256, params)
        bound = log.bind(provider=adapter.name, request_hash=rh[:12], run_id=str(run_id))

        if self._mode is ProviderMode.REPLAY:
            return await self._replay(adapter, asset, rh, params, run_id)

        cached = await self._cached_body(adapter.name, rh)
        if cached is not None:
            artefact_id, body = cached
            bound.info("provider.cache_hit")
            self._maybe_record(adapter, asset, rh, params, body, "application/json", None)
            return await self._finish(
                adapter, rh, params, run_id, ProviderCallStatus.CACHED, body, artefact_id, 0, None
            )

        breaker = self._breakers.get(adapter.name)
        if not breaker.allow():
            bound.warning("provider.breaker_open")
            return await self._record_only(
                adapter, rh, params, run_id, ProviderCallStatus.SKIPPED_BREAKER, "circuit open"
            )

        if adapter.requires_public_url and asset.public_url is None:
            return await self._record_only(
                adapter,
                rh,
                params,
                run_id,
                ProviderCallStatus.ERROR,
                "provider needs a public image URL and none is configured",
            )

        policy = self._policies.get(adapter.quota_key)
        reserved = adapter.unit_cost if policy else 0
        if policy is not None:
            try:
                async with self._sessions.begin() as session:
                    await quota.debit(session, policy, reserved, self._clock())
            except quota.QuotaExhausted as exc:
                bound.warning("provider.quota_exhausted", detail=str(exc))
                return await self._record_only(
                    adapter, rh, params, run_id, ProviderCallStatus.SKIPPED_QUOTA, str(exc)
                )

        started = time.monotonic()
        try:
            raw = await self._call_with_retries(adapter, asset)
        except ProviderError as exc:
            breaker.record_failure()
            if policy is not None and not policy.charges_failed_calls:
                async with self._sessions.begin() as session:
                    await quota.refund(session, policy, reserved, self._clock())
                reserved = 0
            bound.warning("provider.failed", error=str(exc))
            return await self._record_only(
                adapter,
                rh,
                params,
                run_id,
                ProviderCallStatus.ERROR,
                str(exc),
                units=reserved,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        breaker.record_success()
        self._maybe_record(adapter, asset, rh, params, raw.body, raw.content_type, raw.units)
        spent = await self._reconcile(policy, reserved, raw.units)
        latency_ms = int((time.monotonic() - started) * 1000)
        bound.info("provider.ok", units=spent, latency_ms=latency_ms)
        return await self._finish(
            adapter,
            rh,
            params,
            run_id,
            ProviderCallStatus.OK,
            raw.body,
            None,
            spent,
            latency_ms,
            content_type=raw.content_type,
        )

    async def _replay(
        self,
        adapter: ProviderAdapter,
        asset: AssetRef,
        rh: str,
        params: dict[str, object],
        run_id: uuid.UUID | None,
    ) -> ProviderOutcome:
        assert self._fixtures is not None
        recording = self._fixtures.find(adapter.name, rh)
        if recording is None:
            message = (
                f"replay mode: no recording for provider '{adapter.name}' and image "
                f"{asset.sha256[:12]} (request {rh})"
            )
            log.error("provider.replay_missing", provider=adapter.name, request_hash=rh)
            return await self._record_only(
                adapter, rh, params, run_id, ProviderCallStatus.ERROR, message
            )
        return await self._finish(
            adapter,
            rh,
            params,
            run_id,
            ProviderCallStatus.REPLAYED,
            recording.body_bytes(),
            None,
            0,
            None,
            content_type=recording.content_type,
        )

    def _maybe_record(
        self,
        adapter: ProviderAdapter,
        asset: AssetRef,
        rh: str,
        params: dict[str, object],
        body: bytes,
        content_type: str,
        units: int | None,
    ) -> None:
        if self._mode is not ProviderMode.RECORD:
            return
        assert self._fixtures is not None
        path = self._fixtures.write(
            provider=adapter.name,
            rh=rh,
            asset_sha256=asset.sha256,
            params=dict(params),
            body=body,
            content_type=content_type,
            units=units,
            recorded_at=self._clock(),
            secrets=self._redact,
        )
        log.info("provider.recorded", provider=adapter.name, path=str(path))

    async def _call_with_retries(self, adapter: ProviderAdapter, asset: AssetRef) -> RawResponse:
        last: ProviderError | None = None
        for attempt in range(1, self._retry.attempts + 1):
            try:
                async with asyncio.timeout(self._retry.timeout_s):
                    return await adapter.fetch(asset, self._http)
            except ProviderError as exc:
                last = exc
            except TimeoutError:
                last = ProviderError(f"timed out after {self._retry.timeout_s}s", retryable=True)
            except httpx.TransportError as exc:
                last = ProviderError(f"transport error: {exc!r}", retryable=True)
            if not last.retryable or attempt == self._retry.attempts:
                break
            await self._sleep(self._retry.delay(attempt))
        assert last is not None
        raise last

    async def _reconcile(
        self, policy: quota.QuotaPolicy | None, reserved: int, reported: int | None
    ) -> int:
        """Adjust the reservation when the provider reports what it actually charged."""
        if policy is None or reported is None or reported == reserved:
            return reserved
        async with self._sessions.begin() as session:
            if reported < reserved:
                await quota.refund(session, policy, reserved - reported, self._clock())
            else:
                try:
                    await quota.debit(session, policy, reported - reserved, self._clock())
                except quota.QuotaExhausted:
                    log.warning("provider.overspend_reported", provider=policy.key)
        return reported

    async def _cached_body(self, provider: str, rh: str) -> tuple[uuid.UUID, bytes] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(Artefact.id, Artefact.storage_key)
                    .join(ProviderCall, ProviderCall.raw_artefact_id == Artefact.id)
                    .where(
                        ProviderCall.provider == provider,
                        ProviderCall.request_hash == rh,
                        ProviderCall.status == ProviderCallStatus.OK,
                    )
                    .order_by(ProviderCall.created_at.desc())
                    .limit(1)
                )
            ).first()
        if row is None:
            return None
        return row.id, await self._blobs.get(row.storage_key)

    async def _finish(
        self,
        adapter: ProviderAdapter,
        rh: str,
        params: dict[str, object],
        run_id: uuid.UUID | None,
        status: ProviderCallStatus,
        body: bytes,
        artefact_id: uuid.UUID | None,
        units: int,
        latency_ms: int | None,
        *,
        content_type: str = "application/json",
    ) -> ProviderOutcome:
        error: str | None = None
        hits: list[CandidateHit] = []
        try:
            hits = adapter.parse(body)
        except Exception as exc:  # a response we cannot parse is kept, and reported
            error = f"parse error: {exc!r}"
            status = ProviderCallStatus.ERROR
        async with self._sessions.begin() as session:
            if artefact_id is None:
                artefact = await store_artefact(
                    session,
                    self._blobs,
                    data=body,
                    kind=ArtefactKind.PROVIDER_RAW,
                    content_type=content_type,
                    source_url=None,
                )
                artefact_id = artefact.id
            call = ProviderCall(
                run_id=run_id,
                provider=adapter.name,
                request_hash=rh,
                params=params,
                status=status,
                raw_artefact_id=artefact_id,
                units=units,
                latency_ms=latency_ms,
                error=error,
            )
            session.add(call)
            await session.flush()
            call_id = call.id
        return ProviderOutcome(adapter.name, status, call_id, rh, hits, units, error)

    async def _record_only(
        self,
        adapter: ProviderAdapter,
        rh: str,
        params: dict[str, object],
        run_id: uuid.UUID | None,
        status: ProviderCallStatus,
        error: str,
        *,
        units: int = 0,
        latency_ms: int | None = None,
    ) -> ProviderOutcome:
        async with self._sessions.begin() as session:
            call = ProviderCall(
                run_id=run_id,
                provider=adapter.name,
                request_hash=rh,
                params=params,
                status=status,
                units=units,
                latency_ms=latency_ms,
                error=error,
            )
            session.add(call)
            await session.flush()
            call_id = call.id
        return ProviderOutcome(adapter.name, status, call_id, rh, [], units, error)
