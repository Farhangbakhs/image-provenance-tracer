"""Types shared by the test suites (importable, unlike conftest modules, which share a name)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable
from typing import Any, Protocol

import httpx

from origin_core.providers.base import AssetRef, CandidateHit, RawResponse
from origin_core.storage import BlobStore


class SeedRun(Protocol):
    def __call__(
        self, *, image: bytes | None = None, blobs: BlobStore | None = None
    ) -> Awaitable[uuid.UUID]: ...


class ScriptedProvider:
    """Test double standing in for a reverse-image engine: returns the given hits."""

    name: str = "scripted"
    quota_key: str = "scripted"
    unit_cost: int = 0
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("nobody (test)",)

    def __init__(self, hits: list[dict[str, Any]], *, name: str = "scripted") -> None:
        # Provider responses are cached durably by provider name, image and parameters, so
        # tests that query the same image must give their doubles different names.
        self.name = name
        self._body = json.dumps(hits).encode()

    def params(self) -> dict[str, Any]:
        return {}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        return RawResponse(self._body)

    def parse(self, body: bytes) -> list[CandidateHit]:
        return [CandidateHit(**hit) for hit in json.loads(body)]
