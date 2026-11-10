"""Recorded provider responses: written in record mode, served in replay mode.

One file per query at `<root>/<provider>/<request_hash>.json`. Recordings of real responses
live in `fixtures/recordings/` and carry `"synthetic": false`; hand-authored responses live
in `fixtures/synthetic/` and must carry `"synthetic": true`, so a reader can always tell
whether a result came from a real provider.

Run `python -m origin_core.providers.fixtures verify` to check every file's schema, hash and
location.
"""

from __future__ import annotations

import argparse
import base64
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from origin_core.hashing import request_hash, sha256_hex

FORMAT = "origin.provider-recording/v1"
REDACTED = "[REDACTED]"


class Recording(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["origin.provider-recording/v1"] = FORMAT
    provider: str
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    params: dict[str, Any]
    recorded_at: datetime
    synthetic: bool
    note: str | None = None
    content_type: str
    units: int | None = None
    body_encoding: Literal["utf-8", "base64"]
    body: str
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    def body_bytes(self) -> bytes:
        if self.body_encoding == "base64":
            return base64.b64decode(self.body)
        return self.body.encode("utf-8")


class FixtureError(Exception):
    pass


def encode_body(body: bytes) -> tuple[Literal["utf-8", "base64"], str]:
    try:
        return "utf-8", body.decode("utf-8")
    except UnicodeDecodeError:
        return "base64", base64.b64encode(body).decode("ascii")


def redact(body: bytes, secrets: tuple[str, ...]) -> bytes:
    for secret in secrets:
        if secret:
            body = body.replace(secret.encode("utf-8"), REDACTED.encode("utf-8"))
    return body


@dataclass(frozen=True)
class FixtureStore:
    """Reads from every root (recordings first), writes to the first root only."""

    roots: tuple[Path, ...]

    def _path(self, root: Path, provider: str, rh: str) -> Path:
        return root / provider / f"{rh}.json"

    def find(self, provider: str, rh: str) -> Recording | None:
        for root in self.roots:
            path = self._path(root, provider, rh)
            if path.exists():
                return load(path)
        return None

    def write(
        self,
        *,
        provider: str,
        rh: str,
        asset_sha256: str,
        params: dict[str, Any],
        body: bytes,
        content_type: str,
        units: int | None,
        recorded_at: datetime,
        secrets: tuple[str, ...] = (),
    ) -> Path:
        clean = redact(body, secrets)
        encoding, text = encode_body(clean)
        recording = Recording(
            provider=provider,
            request_hash=rh,
            asset_sha256=asset_sha256,
            params=params,
            recorded_at=recorded_at,
            synthetic=False,
            content_type=content_type,
            units=units,
            body_encoding=encoding,
            body=text,
            body_sha256=sha256_hex(clean),
        )
        path = self._path(self.roots[0], provider, rh)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path


def load(path: Path) -> Recording:
    """Load and fully validate one recording file."""
    try:
        recording = Recording.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise FixtureError(f"{path}: invalid recording: {exc}") from exc
    if sha256_hex(recording.body_bytes()) != recording.body_sha256:
        raise FixtureError(f"{path}: body does not match body_sha256")
    expected = request_hash(recording.provider, recording.asset_sha256, recording.params)
    if expected != recording.request_hash:
        raise FixtureError(f"{path}: request_hash does not match provider, asset and params")
    if path.stem != recording.request_hash or path.parent.name != recording.provider:
        raise FixtureError(f"{path}: file is not at <provider>/<request_hash>.json")
    return recording


def verify(recordings_dir: Path, synthetic_dir: Path) -> list[str]:
    """Return a list of problems across both fixture trees (empty means all good)."""
    problems: list[str] = []
    for root, must_be_synthetic in ((recordings_dir, False), (synthetic_dir, True)):
        for path in sorted(root.glob("*/*.json")):
            try:
                recording = load(path)
            except FixtureError as exc:
                problems.append(str(exc))
                continue
            if recording.synthetic is not must_be_synthetic:
                label = "synthetic" if must_be_synthetic else "recordings"
                problems.append(f"{path}: 'synthetic' must be {must_be_synthetic} in {label}/")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="origin_core.providers.fixtures")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("verify", help="validate every recorded and synthetic fixture")
    check.add_argument("--recordings", type=Path, default=Path("fixtures/recordings"))
    check.add_argument("--synthetic", type=Path, default=Path("fixtures/synthetic"))
    args = parser.parse_args(argv)

    problems = verify(args.recordings, args.synthetic)
    for problem in problems:
        print(problem, file=sys.stderr)
    count = sum(1 for root in (args.recordings, args.synthetic) for _ in root.glob("*/*.json"))
    print(f"{count} fixture file(s) checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
