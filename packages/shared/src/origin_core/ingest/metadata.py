"""Embedded metadata (EXIF, XMP, IPTC and more) read with exiftool.

The bytes are piped to exiftool on stdin, so no temporary file is written. The full grouped
output (`-G1`) is kept as evidence; a short summary is derived for the asset panel.

Every value here is a *claim inside the file*: trivial to forge and usually stripped by
platforms. Capture times found here become low-confidence "claimed" dating signals, never
facts. If exiftool is missing or fails, the result says "unavailable", which is different
from "the file has no metadata".
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

EXIFTOOL_TIMEOUT_S = 20.0
#: Groups that describe exiftool's stdin pseudo-file rather than the image.
IGNORED_GROUPS = ("System:",)
IGNORED_KEYS = {"SourceFile"}

# `51 deg 30' 0.00" N`; the hemisphere letter is present only on Composite tags.
_DMS = re.compile(
    r"""(?P<d>\d+(?:\.\d+)?) deg (?P<m>\d+(?:\.\d+)?)' (?P<s>\d+(?:\.\d+)?)"(?: (?P<h>[NSEW]))?"""
)
_OFFSET = re.compile(r"^(?P<sign>[+-])(?P<h>\d{2}):(?P<m>\d{2})$")
_TRAILING_ZONE = re.compile(r"([+-]\d{2}:\d{2}|Z)$")


class MetadataUnavailable(Exception):
    """exiftool could not be run, or its output could not be read."""


@dataclass(frozen=True)
class CaptureTime:
    """A capture time as the file states it. `utc` is set only when the file gives an offset."""

    stated: str
    tag: str
    utc: datetime | None


@dataclass(frozen=True)
class MetadataSummary:
    capture_time: CaptureTime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    software: str | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    credit: str | None = None
    copyright: str | None = None
    groups: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class MetadataResult:
    tool: str
    tool_version: str
    raw: dict[str, Any]
    summary: MetadataSummary


def _first(raw: dict[str, Any], *names: str) -> tuple[str, Any] | None:
    """The first present tag among `names`, matched by tag name in any group, in order."""
    for name in names:
        for key, value in raw.items():
            if key.split(":", 1)[-1] == name and value not in (None, ""):
                return key, value
    return None


def _text(raw: dict[str, Any], *names: str) -> str | None:
    found = _first(raw, *names)
    if found is None:
        return None
    value: Any = found[1]
    if isinstance(value, list):
        return ", ".join(str(item) for item in cast(list[Any], value))
    return str(value).strip() or None


def parse_dms(value: Any, ref: str | None = None) -> float | None:
    """Parse exiftool's `51 deg 30' 0.00" N` into signed decimal degrees.

    The hemisphere comes from the value itself (Composite tags) or from `ref` ("North",
    "S", ...). Without either, the sign is unknown and None is returned rather than guessed.
    """
    if isinstance(value, int | float):
        return float(value)
    match = _DMS.search(str(value))
    if match is None:
        return None
    hemisphere = match["h"] or (ref.strip()[:1].upper() if ref else None)
    if hemisphere not in ("N", "S", "E", "W"):
        return None
    degrees = float(match["d"]) + float(match["m"]) / 60 + float(match["s"]) / 3600
    return -degrees if hemisphere in ("S", "W") else degrees


def _gps(raw: dict[str, Any], axis: str) -> float | None:
    composite = raw.get(f"Composite:GPS{axis}")
    if composite is not None:
        return parse_dms(composite)
    found = _first(raw, f"GPS{axis}")
    if found is None:
        return None
    return parse_dms(found[1], _text(raw, f"GPS{axis}Ref"))


def parse_exif_datetime(stated: str, offset: str | None) -> datetime | None:
    """`2021:03:04 05:06:07` plus `+02:00` -> 2021-03-04T03:06:07Z. None without an offset.

    A bare EXIF time is in the camera's local zone, which the file does not say, so it is
    kept as stated and never silently treated as UTC.
    """
    zone = offset
    clock = stated
    if zone is None:
        trailing = _TRAILING_ZONE.search(stated)
        if trailing is None:
            return None
        zone = "+00:00" if trailing.group(1) == "Z" else trailing.group(1)
        clock = stated[: trailing.start()]
    match = _OFFSET.match(zone)
    if match is None:
        return None
    try:
        local = datetime.strptime(clock.split(".")[0][:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    delta = timedelta(hours=int(match["h"]), minutes=int(match["m"]))
    return local.replace(tzinfo=timezone(delta if match["sign"] == "+" else -delta)).astimezone(UTC)


def _capture_time(raw: dict[str, Any]) -> CaptureTime | None:
    for tag, offset_tag in (
        ("DateTimeOriginal", "OffsetTimeOriginal"),
        ("CreateDate", "OffsetTimeDigitized"),
        ("DateCreated", None),
    ):
        found = _first(raw, tag)
        if found is None:
            continue
        key, value = found
        stated = str(value)
        if stated.startswith("0000"):
            continue
        offset = _text(raw, offset_tag) if offset_tag else None
        return CaptureTime(stated=stated, tag=key, utc=parse_exif_datetime(stated, offset))
    return None


def summarise(raw: dict[str, Any]) -> MetadataSummary:
    groups = sorted({key.split(":", 1)[0] for key in raw if ":" in key})
    return MetadataSummary(
        capture_time=_capture_time(raw),
        camera_make=_text(raw, "Make"),
        camera_model=_text(raw, "Model"),
        software=_text(raw, "Software", "CreatorTool"),
        gps_latitude=_gps(raw, "Latitude"),
        gps_longitude=_gps(raw, "Longitude"),
        credit=_text(raw, "Credit", "Artist", "Creator", "By-line"),
        copyright=_text(raw, "Copyright", "Rights", "CopyrightNotice"),
        groups=groups,
    )


async def read_metadata(data: bytes, *, exiftool: str = "exiftool") -> MetadataResult:
    """Run exiftool over `data` (via stdin) and return its grouped output and a summary."""
    try:
        process = await asyncio.create_subprocess_exec(
            exiftool,
            "-j",  # JSON
            "-G1",  # prefix each tag with its specific group (IFD0, ExifIFD, XMP-dc, IPTC...)
            "-a",  # keep duplicate tags from different groups
            "-struct",  # structured XMP as objects
            "-charset",
            "utf8",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise MetadataUnavailable(f"exiftool could not be started ({exiftool}): {exc}") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(data), EXIFTOOL_TIMEOUT_S)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise MetadataUnavailable(f"exiftool timed out after {EXIFTOOL_TIMEOUT_S}s") from exc
    if process.returncode != 0 and not stdout:
        raise MetadataUnavailable(f"exiftool failed: {stderr.decode(errors='replace').strip()}")
    try:
        parsed: Any = json.loads(stdout)
        entry = dict(cast(dict[str, Any], parsed[0]))
    except (ValueError, IndexError, TypeError, KeyError) as exc:
        raise MetadataUnavailable(f"exiftool output could not be parsed: {exc}") from exc

    version = str(entry.get("ExifTool:ExifToolVersion", "unknown"))
    raw = {
        key: value
        for key, value in entry.items()
        if key not in IGNORED_KEYS and not key.startswith(IGNORED_GROUPS)
    }
    return MetadataResult(tool="exiftool", tool_version=version, raw=raw, summary=summarise(raw))
