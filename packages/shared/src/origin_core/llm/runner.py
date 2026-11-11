"""LLMRunner: every model call is keyed, cached, recorded or replayed, retried and logged.

The request hash covers the provider, the model, the prompt version and the full prompt (system,
user and schema), so an identical question is never paid for twice and a recorded answer can
never be served for a different question. Raw responses are stored as `llm_raw` artefacts and
every call leaves a `provider_calls` row named `llm:<provider>`.

`complete_validated` is the entry point for structured output: it parses the reply into a
Pydantic model, applies a caller-supplied check (for example "every cited id exists"), and on
failure asks again with the error explained, up to a fixed number of attempts.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from origin_core.artefacts import store_artefact
from origin_core.db.models import Artefact, ProviderCall
from origin_core.enums import ArtefactKind, ProviderCallStatus
from origin_core.hashing import request_hash
from origin_core.llm.base import LLMError, LLMProvider, Prompt, RawReply
from origin_core.providers.fixtures import FixtureStore
from origin_core.settings import ProviderMode
from origin_core.storage import BlobStore

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LLMReply:
    text: str
    provider: str
    model: str
    prompt_version: str
    status: ProviderCallStatus
    call_id: uuid.UUID


class LLMOutputRejected(Exception):
    """The model's output never satisfied the schema and checks within the allowed attempts."""


class LLMRunner:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        http: httpx.AsyncClient,
        mode: ProviderMode = ProviderMode.LIVE,
        fixtures: FixtureStore | None = None,
        redact_secrets: tuple[str, ...] = (),
        attempts: int = 3,
    ) -> None:
        if mode is not ProviderMode.LIVE and fixtures is None:
            raise ValueError(f"mode '{mode.value}' needs a FixtureStore")
        self._sessions = sessions
        self._blobs = blobs
        self._http = http
        self._mode = mode
        self._fixtures = fixtures
        self._redact = redact_secrets
        self._attempts = attempts

    @staticmethod
    def _key(provider: LLMProvider, prompt: Prompt) -> tuple[str, str, dict[str, object]]:
        name = f"llm:{provider.name}"
        params: dict[str, object] = {"model": provider.model, "prompt_version": prompt.version}
        return name, request_hash(name, prompt.sha256, params), params

    async def complete(
        self, provider: LLMProvider, prompt: Prompt, *, run_id: uuid.UUID | None = None
    ) -> LLMReply:
        name, rh, params = self._key(provider, prompt)

        if self._mode is ProviderMode.REPLAY:
            assert self._fixtures is not None
            recording = self._fixtures.find(name, rh)
            if recording is None:
                raise LLMError(
                    f"replay mode: no recording for {name} prompt {prompt.version} ({rh})",
                    retryable=False,
                )
            return await self._finish(
                provider,
                prompt,
                rh,
                params,
                run_id,
                recording.body_bytes(),
                ProviderCallStatus.REPLAYED,
            )

        cached = await self._cached(name, rh)
        if cached is not None:
            return await self._finish(
                provider, prompt, rh, params, run_id, cached, ProviderCallStatus.CACHED
            )

        raw = await self._call(provider, prompt)
        if self._mode is ProviderMode.RECORD:
            assert self._fixtures is not None
            self._fixtures.write(
                provider=name,
                rh=rh,
                asset_sha256=prompt.sha256,
                params=dict(params),
                body=raw.body,
                content_type="application/json",
                units=raw.units,
                recorded_at=datetime.now(UTC),
                secrets=self._redact,
            )
        return await self._finish(
            provider, prompt, rh, params, run_id, raw.body, ProviderCallStatus.OK
        )

    async def complete_validated[M: BaseModel](
        self,
        provider: LLMProvider,
        prompt: Prompt,
        model: type[M],
        *,
        check: Callable[[M], str | None] | None = None,
        run_id: uuid.UUID | None = None,
    ) -> tuple[M, LLMReply]:
        """Ask, parse into `model`, run `check` (an error string or None); retry on failure."""
        current = prompt
        problems: list[str] = []
        for attempt in range(1, self._attempts + 1):
            reply = await self.complete(provider, current, run_id=run_id)
            try:
                parsed = model.model_validate_json(reply.text)
            except ValidationError as exc:
                problem = f"output did not match the schema: {exc.errors()[:3]}"
            else:
                problem = check(parsed) if check else None
                if problem is None:
                    return parsed, reply
            problems.append(problem)
            log.warning(
                "llm.output_rejected", prompt=prompt.version, attempt=attempt, problem=problem
            )
            # Ask again, saying what was wrong. A changed prompt is a new request, never a cache hit
            # for the rejected answer.
            current = replace(
                prompt,
                user=prompt.user
                + "\n\nYour previous answer was rejected: "
                + problem
                + "\nAnswer again, following the schema and the rules exactly.",
            )
        raise LLMOutputRejected(f"{prompt.version}: rejected {self._attempts} times: {problems}")

    async def _call(self, provider: LLMProvider, prompt: Prompt) -> RawReply:
        last: LLMError | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                return await provider.complete(prompt, self._http)
            except LLMError as exc:
                last = exc
                if not exc.retryable or attempt == self._attempts:
                    break
                await asyncio.sleep(min(30.0, 2.0**attempt))
        assert last is not None
        raise last

    async def _cached(self, name: str, rh: str) -> bytes | None:
        async with self._sessions() as session:
            key = (
                await session.execute(
                    select(Artefact.storage_key)
                    .join(ProviderCall, ProviderCall.raw_artefact_id == Artefact.id)
                    .where(
                        ProviderCall.provider == name,
                        ProviderCall.request_hash == rh,
                        ProviderCall.status == ProviderCallStatus.OK,
                    )
                    .order_by(ProviderCall.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return await self._blobs.get(key) if key else None

    async def _finish(
        self,
        provider: LLMProvider,
        prompt: Prompt,
        rh: str,
        params: dict[str, object],
        run_id: uuid.UUID | None,
        body: bytes,
        status: ProviderCallStatus,
    ) -> LLMReply:
        text = provider.text(body)
        async with self._sessions.begin() as session:
            artefact = await store_artefact(
                session,
                self._blobs,
                data=body,
                kind=ArtefactKind.LLM_RAW,
                content_type="application/json",
            )
            call = ProviderCall(
                run_id=run_id,
                provider=f"llm:{provider.name}",
                request_hash=rh,
                params=params,
                status=status,
                raw_artefact_id=artefact.id,
                units=1 if status is ProviderCallStatus.OK else 0,
            )
            session.add(call)
            await session.flush()
            call_id = call.id
        return LLMReply(text, provider.name, provider.model, prompt.version, status, call_id)
