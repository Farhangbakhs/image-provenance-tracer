import os
import uuid
from pathlib import Path

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from origin_core.hashing import sha256_hex
from origin_core.storage import BlobIntegrityError, FilesystemBlobStore, S3BlobStore, blob_key


async def test_filesystem_store_is_content_addressed(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    await store.ensure_ready()
    first = await store.put(b"hello", "text/plain")
    again = await store.put(b"hello", "text/plain")
    assert first == again
    assert first.key == blob_key(sha256_hex(b"hello"))
    assert await store.exists(first.key)
    assert await store.get(first.key) == b"hello"


async def test_filesystem_store_detects_tampering(tmp_path: Path) -> None:
    store = FilesystemBlobStore(tmp_path)
    blob = await store.put(b"original", "text/plain")
    (tmp_path / blob.key).write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        await store.get(blob.key)


@pytest.mark.s3
async def test_s3_store_round_trip() -> None:
    store = S3BlobStore(
        bucket=f"origin-test-{uuid.uuid4().hex[:8]}",
        endpoint_url=os.environ.get("TEST_S3_ENDPOINT", "http://localhost:8333"),
        region="us-east-1",
        access_key="origin",
        secret_key="origin-dev-secret",
    )
    try:
        await store.ensure_ready()
    except (BotoCoreError, ClientError) as exc:
        if os.environ.get("ORIGIN_REQUIRE_S3") == "1":
            raise
        pytest.skip(f"S3 endpoint not reachable ({exc})")
    blob = await store.put(b"\x89PNG bytes", "image/png")
    assert await store.exists(blob.key)
    assert not await store.exists(blob_key("0" * 64))
    assert await store.get(blob.key) == b"\x89PNG bytes"
