"""The dating rule, case by case. Each test is one situation an analyst meets."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from origin_core.dating.rule import DEFAULT_READING, RULE_VERSION, Signal, date_sighting
from origin_core.enums import BoundType, Confidence, DateConfidence, EvidenceKind


def t(day: int, hour: int = 0) -> datetime:
    return datetime(2024, 3, day, hour, tzinfo=UTC)


def sig(
    id: str, kind: EvidenceKind, value: datetime, confidence: Confidence | None = None
) -> Signal:
    bound, default_confidence = DEFAULT_READING[kind]
    return Signal(id, kind, value, bound, confidence or default_confidence)


OBSERVED = sig("fetch", EvidenceKind.OBSERVED, t(30))


def test_only_our_fetch_means_existed_no_later_than_then() -> None:
    result = date_sighting([OBSERVED])
    assert (result.lower, result.upper) == (None, t(30))
    assert result.confidence is DateConfidence.HIGH
    assert result.deciding == OBSERVED
    assert result.rule_version == RULE_VERSION


def test_earliest_archive_capture_sets_the_ceiling() -> None:
    wayback = sig("wb", EvidenceKind.WAYBACK_PAGE, t(10))
    crawl = sig("crawl", EvidenceKind.PROVIDER_CRAWL, t(12))
    result = date_sighting([OBSERVED, crawl, wayback])
    assert result.upper == t(10)
    assert result.deciding == wayback


def test_platform_timestamp_collapses_the_interval() -> None:
    post = sig("tg", EvidenceKind.PLATFORM, t(5, 14))
    result = date_sighting([OBSERVED, sig("wb", EvidenceKind.WAYBACK_PAGE, t(10)), post])
    assert (result.lower, result.upper) == (t(5, 14), t(5, 14))
    assert result.confidence is DateConfidence.HIGH
    assert result.deciding == post


def test_published_date_narrows_but_stays_a_claim() -> None:
    published = sig("meta", EvidenceKind.PAGE_METADATA, t(8))
    result = date_sighting([OBSERVED, sig("wb", EvidenceKind.WAYBACK_PAGE, t(10)), published])
    assert (result.lower, result.upper) == (t(8), t(10))
    assert result.confidence is DateConfidence.MEDIUM
    assert result.deciding == published


def test_a_high_confidence_claim_is_still_capped_at_medium() -> None:
    published = sig("meta", EvidenceKind.PAGE_METADATA, t(8), Confidence.HIGH)
    assert date_sighting([OBSERVED, published]).confidence is DateConfidence.MEDIUM


def test_claimed_date_after_an_archive_capture_is_rejected() -> None:
    # The page says it was published on the 20th, but the archive saw it on the 10th.
    backdated = sig("meta", EvidenceKind.PAGE_METADATA, t(20))
    result = date_sighting([OBSERVED, sig("wb", EvidenceKind.WAYBACK_PAGE, t(10)), backdated])
    assert result.upper == t(10) and result.lower is None
    assert result.deciding is not None and result.deciding.id == "wb"
    assert any("contradicts" in note for note in result.notes)


def test_capture_time_is_a_floor() -> None:
    exif = sig("exif", EvidenceKind.EXIF, t(3))
    result = date_sighting([OBSERVED, exif])
    assert (result.lower, result.upper) == (t(3), t(30))


def test_impossible_capture_time_is_noted_not_used() -> None:
    # A camera clock claiming a time after the archive already had the image.
    exif = sig("exif", EvidenceKind.EXIF, t(25))
    result = date_sighting([OBSERVED, sig("wb", EvidenceKind.WAYBACK_IMAGE, t(10)), exif])
    assert result.lower is None
    assert any("later than the sighting was already observed" in note for note in result.notes)


def test_claim_before_the_picture_existed_is_rejected() -> None:
    signed = sig("c2pa", EvidenceKind.C2PA, t(6))
    early = sig("meta", EvidenceKind.PAGE_METADATA, t(2))
    result = date_sighting([OBSERVED, signed, early])
    assert result.lower == t(6)
    assert result.deciding is not None and result.deciding.id == "fetch"


def test_disagreeing_exact_timestamps_are_flagged_and_earliest_used() -> None:
    a = sig("a", EvidenceKind.PLATFORM, t(4))
    b = sig("b", EvidenceKind.PLATFORM, t(7))
    result = date_sighting([OBSERVED, b, a])
    assert result.deciding == a
    assert any("disagree" in note for note in result.notes)


def test_no_signals_means_unknown() -> None:
    result = date_sighting([])
    assert result.confidence is DateConfidence.UNKNOWN
    assert (result.lower, result.upper, result.deciding) == (None, None, None)


def test_naive_datetimes_are_refused() -> None:
    naive = Signal(
        "x", EvidenceKind.OBSERVED, datetime(2024, 3, 1), BoundType.NO_LATER_THAN, Confidence.HIGH
    )
    with pytest.raises(ValueError, match="naive"):
        date_sighting([naive])
