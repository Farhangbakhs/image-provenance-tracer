"""Persist bytes as artefacts: blob first, then the database row that describes it."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from origin_core.db.models import Artefact
from origin_core.enums import ArtefactKind
from origin_core.storage import BlobStore


async def store_artefact(
    session: AsyncSession,
    blobs: BlobStore,
    *,
    data: bytes,
    kind: ArtefactKind,
    content_type: str,
    source_url: str | None = None,
    http_status: int | None = None,
    http_headers: dict[str, Any] | None = None,
    fetched_at: datetime | None = None,
) -> Artefact:
    blob = await blobs.put(data, content_type)
    artefact = Artefact(
        kind=kind,
        sha256=blob.sha256,
        storage_key=blob.key,
        content_type=content_type,
        byte_size=blob.byte_size,
        source_url=source_url,
        http_status=http_status,
        http_headers=http_headers,
    )
    if fetched_at is not None:
        artefact.fetched_at = fetched_at
    session.add(artefact)
    await session.flush()
    return artefact
