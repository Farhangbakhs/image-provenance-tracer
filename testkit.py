"""Types shared by the test suites (importable, unlike conftest modules, which share a name)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Protocol

from origin_core.storage import BlobStore


class SeedRun(Protocol):
    def __call__(
        self, *, image: bytes | None = None, blobs: BlobStore | None = None
    ) -> Awaitable[uuid.UUID]: ...
