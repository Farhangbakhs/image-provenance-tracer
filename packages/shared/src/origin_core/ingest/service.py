"""Ingest an upload into a case: validate, store, fingerprint, read metadata and credentials.

Everything here is fast enough to do while the analyst waits, so an unsafe or unreadable file
is refused at upload time. The SSCD embedding is added later by the worker's ingest stage.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from origin_core.db.models import Asset, AuditEvent
from origin_core.enums import Actor
from origin_core.hashing import sha256_hex
from origin_core.ingest.c2pa import C2PAResult, TrustAnchors, read_c2pa
from origin_core.ingest.hashes import Fingerprints, fingerprint
from origin_core.ingest.metadata import MetadataUnavailable, read_metadata
from origin_core.ingest.store import store_upload
from origin_core.ingest.validate import ValidatedImage, decode_rgb, validate_upload
from origin_core.storage import BlobStore


@dataclasses.dataclass(frozen=True)
class IngestLimits:
    max_bytes: int
    max_pixels: int


@dataclasses.dataclass(frozen=True)
class IngestResult:
    asset: Asset
    created: bool


def _jsonable(value: Any) -> Any:
    """Dataclasses, enums and datetimes to plain JSON values."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in cast(dict[Any, Any], value).items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in cast(list[Any], value)]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _validate_and_fingerprint(
    data: bytes, limits: IngestLimits
) -> tuple[ValidatedImage, Fingerprints]:
    image = validate_upload(data, max_bytes=limits.max_bytes, max_pixels=limits.max_pixels)
    return image, fingerprint(data, decode_rgb(data, image.format))


async def ingest_upload(
    session: AsyncSession,
    blobs: BlobStore,
    *,
    case_id: uuid.UUID,
    data: bytes,
    filename: str | None,
    limits: IngestLimits,
    exiftool: str,
    trust: TrustAnchors | None = None,
) -> IngestResult:
    """Add an image to a case. Re-uploading identical bytes returns the existing asset.

    Raises UploadRejected for anything that is not a safe, readable image.
    """
    existing = (
        await session.execute(
            select(Asset).where(Asset.case_id == case_id, Asset.sha256 == sha256_hex(data))
        )
    ).scalar_one_or_none()
    if existing is not None:
        return IngestResult(asset=existing, created=False)

    # Decoding and perceptual hashing are CPU-bound: keep them off the event loop.
    image, prints = await asyncio.to_thread(_validate_and_fingerprint, data, limits)

    metadata: dict[str, Any]
    try:
        result = await read_metadata(data, exiftool=exiftool)
        metadata = {
            "status": "ok",
            "tool": result.tool,
            "tool_version": result.tool_version,
            "summary": _jsonable(result.summary),
            "raw": result.raw,
        }
    except MetadataUnavailable as exc:
        metadata = {"status": "unavailable", "error": str(exc)}

    credentials: C2PAResult = await read_c2pa(data, image.mime, trust)
    stored = await store_upload(session, blobs, image)

    asset = Asset(
        case_id=case_id,
        original_artefact_id=stored.original.id,
        display_artefact_id=stored.display.id,
        original_filename=filename,
        content_type=image.mime,
        width=image.width,
        height=image.height,
        sha256=prints.sha256,
        phash=prints.phash,
        dhash=prints.dhash,
        pdq=prints.pdq,
        pdq_quality=prints.pdq_quality,
        metadata_raw=metadata,
        c2pa_state=credentials.state,
        c2pa_report=_jsonable(credentials),
    )
    session.add(asset)
    await session.flush()
    session.add(
        AuditEvent(
            case_id=case_id,
            actor=Actor.ANALYST,
            action="asset.uploaded",
            subject_type="asset",
            subject_id=asset.id,
            detail={
                "sha256": prints.sha256,
                "filename": filename,
                "bytes": len(data),
                "c2pa_state": credentials.state.value,
                "metadata": metadata["status"],
            },
        )
    )
    await session.flush()
    return IngestResult(asset=asset, created=True)
