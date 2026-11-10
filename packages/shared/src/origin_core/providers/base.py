"""The provider adapter protocol.

An adapter knows how to ask one reverse-image engine about one image, and how to turn the
engine's raw response into candidate hits. It does not cache, meter quota, retry, record or
replay: the ProviderRunner does all of that uniformly for every adapter.

Adapters are split into `fetch` (network) and `parse` (pure) so that recorded responses can be
re-parsed offline, and contract tests can run against recordings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class AssetRef:
    """What an adapter may know about the query image."""

    id: str
    sha256: str
    content_type: str
    data: bytes = field(repr=False)
    width: int
    height: int
    public_url: str | None = None


class CandidateHit(BaseModel):
    """One unverified hit. Becomes a `candidates` row; never treated as evidence."""

    model_config = ConfigDict(frozen=True)

    page_url: str | None = None
    image_url: str | None = None
    provider_date: datetime | None = None
    rank: int | None = None
    title: str | None = None
    raw: dict[str, Any] = {}


@dataclass(frozen=True)
class RawResponse:
    body: bytes
    content_type: str = "application/json"
    #: Units actually spent, when the provider reports it; otherwise the adapter's unit cost.
    units: int | None = None


class ProviderError(Exception):
    """A failed provider call. `retryable` errors are retried with backoff."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class ProviderAdapter(Protocol):
    #: Stable identifier, used in cache keys, fixtures and the database.
    name: str
    #: Quota bucket. Adapters that share a vendor plan share a key (Lens and Yandex: "serpapi").
    quota_key: str
    #: Units charged per call against the quota bucket.
    unit_cost: int
    #: True when the provider can only fetch the image from a public URL.
    requires_public_url: bool
    #: Third parties that receive the image bytes or URL; shown on the intake screen.
    recipients: tuple[str, ...]

    def params(self) -> dict[str, Any]:
        """Request parameters that change the result. Never includes secrets."""
        ...

    async def fetch(self, asset: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        """Call the provider. Raise ProviderError on failure."""
        ...

    def parse(self, body: bytes) -> list[CandidateHit]:
        """Turn a raw response body into candidate hits. Pure; no I/O."""
        ...
