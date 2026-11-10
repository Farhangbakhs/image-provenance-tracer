"""Content-addressed blob storage.

Every byte sequence ORIGIN keeps (uploads, fetched images and pages, raw provider and model
responses) is stored under its SHA-256, so the same bytes are stored once and any key can be
re-verified against its content.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from origin_core.hashing import sha256_hex
from origin_core.settings import BlobBackend, Settings


@dataclass(frozen=True)
class StoredBlob:
    key: str
    sha256: str
    byte_size: int
    content_type: str


def blob_key(sha256: str) -> str:
    return f"sha256/{sha256[:2]}/{sha256}"


class BlobIntegrityError(RuntimeError):
    """Stored bytes no longer match the hash in their key."""


class BlobStore(Protocol):
    async def ensure_ready(self) -> None: ...
    async def put(self, data: bytes, content_type: str) -> StoredBlob: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...


def _error_code(exc: ClientError) -> str:
    response: dict[str, Any] = dict(exc.response)  # pyright: ignore[reportUnknownArgumentType]
    error: Any = response.get("Error") or {}
    return str(error.get("Code", ""))


def _verify(key: str, data: bytes) -> bytes:
    expected = key.rsplit("/", 1)[-1]
    if sha256_hex(data) != expected:
        raise BlobIntegrityError(f"content of {key} does not match its hash")
    return data


class FilesystemBlobStore:
    """Blobs as files under a root directory. Used by tests and the offline demo."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: str) -> Path:
        return self._root / key

    async def ensure_ready(self) -> None:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)

    async def put(self, data: bytes, content_type: str) -> StoredBlob:
        sha = sha256_hex(data)
        key = blob_key(sha)
        path = self._path(key)

        def write() -> None:
            if path.exists():
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)

        await asyncio.to_thread(write)
        return StoredBlob(key=key, sha256=sha, byte_size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        return _verify(key, await asyncio.to_thread(self._path(key).read_bytes))

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).exists)


class S3BlobStore:
    """Blobs in an S3-compatible bucket (SeaweedFS locally, Cloudflare R2 deployed)."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        self._bucket = bucket
        self._client: Any = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
            ),
        )

    async def ensure_ready(self) -> None:
        def ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                if _error_code(exc) not in {"404", "NoSuchBucket"}:
                    raise
                self._client.create_bucket(Bucket=self._bucket)

        await asyncio.to_thread(ensure)

    async def put(self, data: bytes, content_type: str) -> StoredBlob:
        sha = sha256_hex(data)
        key = blob_key(sha)
        if not await self.exists(key):
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        return StoredBlob(key=key, sha256=sha, byte_size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body

        return _verify(key, await asyncio.to_thread(read))

    async def exists(self, key: str) -> bool:
        def head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if _error_code(exc) in {"404", "NoSuchKey"}:
                    return False
                raise
            return True

        return await asyncio.to_thread(head)


def make_blob_store(settings: Settings) -> BlobStore:
    if settings.blob_backend is BlobBackend.FILESYSTEM:
        return FilesystemBlobStore(settings.blob_dir)
    return S3BlobStore(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
    )
