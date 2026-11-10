from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from origin_core.enums import ArtefactKind
from origin_core.hashing import sha256_hex
from origin_core.ingest.store import store_upload
from origin_core.ingest.validate import validate_upload
from origin_core.storage import FilesystemBlobStore

from .images import jpeg

pytestmark = pytest.mark.db


async def test_store_upload_keeps_original_and_display(db: AsyncSession, tmp_path: Path) -> None:
    data = jpeg()
    image = validate_upload(data, max_bytes=10_000_000, max_pixels=10_000_000)
    blobs = FilesystemBlobStore(tmp_path)

    stored = await store_upload(db, blobs, image)

    assert stored.original.kind is ArtefactKind.ORIGINAL
    assert stored.original.sha256 == sha256_hex(data)
    assert stored.original.content_type == "image/jpeg"
    assert await blobs.get(stored.original.storage_key) == data
    assert stored.display.kind is ArtefactKind.DISPLAY
    assert stored.display.sha256 == sha256_hex(image.display)
    assert stored.display.byte_size == len(image.display)
