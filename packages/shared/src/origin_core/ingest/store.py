"""Persist a validated upload: the untouched original and the re-encoded display copy."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from origin_core.artefacts import store_artefact
from origin_core.db.models import Artefact
from origin_core.enums import ArtefactKind
from origin_core.ingest.validate import ValidatedImage
from origin_core.storage import BlobStore


@dataclass(frozen=True)
class StoredUpload:
    original: Artefact
    display: Artefact


async def store_upload(
    session: AsyncSession, blobs: BlobStore, image: ValidatedImage
) -> StoredUpload:
    original = await store_artefact(
        session, blobs, data=image.data, kind=ArtefactKind.ORIGINAL, content_type=image.mime
    )
    display = await store_artefact(
        session,
        blobs,
        data=image.display,
        kind=ArtefactKind.DISPLAY,
        content_type=image.display_mime,
    )
    return StoredUpload(original=original, display=display)
