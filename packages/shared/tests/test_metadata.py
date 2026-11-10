"""Metadata via exiftool: grouped raw output kept, summary derived, failures reported honestly."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime

import pytest
from PIL import Image

from origin_core.ingest.metadata import (
    MetadataUnavailable,
    parse_dms,
    parse_exif_datetime,
    read_metadata,
    summarise,
)

from .images import encode, jpeg, scene

EXIFTOOL = os.environ.get("EXIFTOOL_PATH", "exiftool")


def _require_exiftool() -> None:
    if shutil.which(EXIFTOOL) is None:
        if os.environ.get("ORIGIN_REQUIRE_SERVICES") == "1":
            pytest.fail(f"exiftool not found ({EXIFTOOL})")
        pytest.skip("exiftool not installed")


def _tagged_jpeg() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "TestMake"  # Make
    exif[0x0110] = "TestModel"  # Model
    exif[0x0131] = "TestSoftware 2.1"  # Software
    exif[0x8298] = "(c) Example Agency"  # Copyright
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = "2021:03:04 05:06:07"  # DateTimeOriginal
    sub[0x9011] = "+02:00"  # OffsetTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (51.0, 30.0, 0.0)
    gps[3], gps[4] = "W", (0.0, 7.0, 30.0)
    return jpeg(scene(64, 48), exif=exif.tobytes())


async def test_reads_grouped_tags_and_summarises() -> None:
    _require_exiftool()
    result = await read_metadata(_tagged_jpeg(), exiftool=EXIFTOOL)

    assert result.tool == "exiftool" and result.tool_version not in ("", "unknown")
    assert result.raw["IFD0:Make"] == "TestMake"
    assert "SourceFile" not in result.raw
    assert not any(key.startswith("System:") for key in result.raw)

    summary = result.summary
    assert (summary.camera_make, summary.camera_model) == ("TestMake", "TestModel")
    assert summary.software == "TestSoftware 2.1"
    assert summary.copyright == "(c) Example Agency"
    assert summary.capture_time is not None
    assert summary.capture_time.stated == "2021:03:04 05:06:07"
    assert summary.capture_time.utc == datetime(2021, 3, 4, 3, 6, 7, tzinfo=UTC)
    assert summary.gps_latitude == pytest.approx(51.5)
    assert summary.gps_longitude == pytest.approx(-0.125)
    assert "ExifIFD" in summary.groups


async def test_image_without_metadata_has_empty_summary() -> None:
    _require_exiftool()
    result = await read_metadata(encode(scene(32, 32), "PNG"), exiftool=EXIFTOOL)
    assert result.summary.capture_time is None
    assert result.summary.camera_make is None
    assert result.raw["File:FileType"] == "PNG"


async def test_missing_exiftool_is_unavailable_not_empty() -> None:
    with pytest.raises(MetadataUnavailable, match="could not be started"):
        await read_metadata(jpeg(), exiftool="definitely-not-exiftool-on-path")


def test_capture_time_without_offset_is_not_assumed_utc() -> None:
    assert parse_exif_datetime("2021:03:04 05:06:07", None) is None
    assert parse_exif_datetime("2021:03:04 05:06:07", "-05:30") == datetime(
        2021, 3, 4, 10, 36, 7, tzinfo=UTC
    )
    assert parse_exif_datetime("2021:03:04 05:06:07Z", None) == datetime(
        2021, 3, 4, 5, 6, 7, tzinfo=UTC
    )
    assert parse_exif_datetime("not a date", "+00:00") is None


def test_parse_dms() -> None:
    assert parse_dms("51 deg 30' 0.00\" N") == pytest.approx(51.5)
    assert parse_dms("33 deg 52' 4.80\" S") == pytest.approx(-33.868)
    assert parse_dms("0 deg 7' 30.00\"", "West") == pytest.approx(-0.125)
    assert parse_dms("0 deg 7' 30.00\"") is None  # hemisphere unknown: do not guess a sign
    assert parse_dms(12.5) == 12.5
    assert parse_dms("garbage") is None


def test_gps_without_composite_uses_reference_tags() -> None:
    summary = summarise(
        {
            "GPS:GPSLatitude": "51 deg 30' 0.00\"",
            "GPS:GPSLatitudeRef": "North",
            "GPS:GPSLongitude": "0 deg 7' 30.00\"",
            "GPS:GPSLongitudeRef": "West",
        }
    )
    assert summary.gps_latitude == pytest.approx(51.5)
    assert summary.gps_longitude == pytest.approx(-0.125)


def test_zeroed_capture_time_is_ignored() -> None:
    summary = summarise({"ExifIFD:DateTimeOriginal": "0000:00:00 00:00:00"})
    assert summary.capture_time is None
