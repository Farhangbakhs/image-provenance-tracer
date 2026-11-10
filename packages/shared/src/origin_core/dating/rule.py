"""The dating rule: many timestamp signals for one sighting -> one interval and a confidence.

A sighting's date is *when that copy first appeared at that URL*, and it is never a single
fact. Each signal says something different:

  exact            the platform's own post time            -> the interval collapses to it
  no_later_than    archive capture, crawl, ORIGIN's fetch   -> caps the interval from above
  no_earlier_than  capture or signing time of the picture   -> floors it from below
  claimed          a page's stated publication date         -> narrows the floor, if plausible

Rule v1, applied in this order:

1. upper = the earliest no_later_than signal (there is always one: ORIGIN's own fetch).
2. lower = the latest no_earlier_than signal that does not exceed upper. A floor above the
   ceiling is a contradiction (usually a wrong camera clock) and is recorded, not used.
3. exact signals inside [lower, upper] collapse the interval to the earliest of them, with
   that signal's confidence. Exact signals that disagree by more than 24 hours are flagged.
4. Otherwise the earliest claimed signal inside [lower, upper] raises lower to itself; its
   confidence is capped at medium because it is a claim, not a proof.
5. Otherwise the interval is [lower, upper] and the confidence is the upper bound's: the
   statement made is "existed no later than".

The deciding signal is the one that set the value people read first: the exact or claimed
time when one was used, otherwise the upper bound.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from origin_core.enums import BoundType, Confidence, DateConfidence, EvidenceKind

RULE_VERSION = "dating.v1"
EXACT_DISAGREEMENT = timedelta(hours=24)

_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


@dataclass(frozen=True)
class Signal:
    id: str
    kind: EvidenceKind
    value: datetime
    bound: BoundType
    confidence: Confidence


@dataclass(frozen=True)
class DatingResult:
    lower: datetime | None
    upper: datetime | None
    confidence: DateConfidence
    deciding: Signal | None
    rule_version: str = RULE_VERSION
    notes: list[str] = field(default_factory=list[str])


def _cap(confidence: Confidence, ceiling: Confidence) -> Confidence:
    return confidence if _RANK[confidence] <= _RANK[ceiling] else ceiling


def _within(value: datetime, lower: datetime | None, upper: datetime | None) -> bool:
    return (lower is None or value >= lower) and (upper is None or value <= upper)


def date_sighting(signals: list[Signal]) -> DatingResult:
    for signal in signals:
        if signal.value.tzinfo is None:
            raise ValueError(
                f"signal {signal.id} has a naive datetime; all times must be UTC-aware"
            )
    notes: list[str] = []

    ceilings = sorted(
        (s for s in signals if s.bound is BoundType.NO_LATER_THAN), key=lambda s: s.value
    )
    upper_signal = ceilings[0] if ceilings else None
    upper = upper_signal.value if upper_signal else None

    lower: datetime | None = None
    for floor in sorted(
        (s for s in signals if s.bound is BoundType.NO_EARLIER_THAN), key=lambda s: s.value
    ):
        if upper is not None and floor.value > upper:
            notes.append(
                f"{floor.kind.value} {floor.value.isoformat()} is later than the sighting was "
                f"already observed ({upper.isoformat()}); ignored as contradictory"
            )
            continue
        lower = floor.value

    exact = sorted((s for s in signals if s.bound is BoundType.EXACT), key=lambda s: s.value)
    consistent_exact = [s for s in exact if _within(s.value, lower, upper)]
    for s in exact:
        if s not in consistent_exact:
            notes.append(
                f"{s.kind.value} {s.value.isoformat()} falls outside the proven bounds; ignored"
            )
    if (
        len(consistent_exact) > 1
        and consistent_exact[-1].value - consistent_exact[0].value > EXACT_DISAGREEMENT
    ):
        notes.append("exact timestamps disagree by more than 24 hours; the earliest is used")
    if consistent_exact:
        chosen = consistent_exact[0]
        return DatingResult(
            lower=chosen.value,
            upper=chosen.value,
            confidence=DateConfidence(chosen.confidence.value),
            deciding=chosen,
            notes=notes,
        )

    claimed = sorted((s for s in signals if s.bound is BoundType.CLAIMED), key=lambda s: s.value)
    plausible = [s for s in claimed if _within(s.value, lower, upper)]
    for s in claimed:
        if s not in plausible:
            notes.append(
                f"{s.kind.value} {s.value.isoformat()} contradicts the proven bounds; ignored"
            )
    if plausible:
        chosen = plausible[0]
        return DatingResult(
            lower=chosen.value,
            upper=upper,
            confidence=DateConfidence(_cap(chosen.confidence, Confidence.MEDIUM).value),
            deciding=chosen,
            notes=notes,
        )

    if upper_signal is None:
        return DatingResult(
            lower=lower, upper=None, confidence=DateConfidence.UNKNOWN, deciding=None, notes=notes
        )
    return DatingResult(
        lower=lower,
        upper=upper,
        confidence=DateConfidence(upper_signal.confidence.value),
        deciding=upper_signal,
        notes=notes,
    )


#: How each evidence kind is read, for code that creates signals.
DEFAULT_READING: dict[EvidenceKind, tuple[BoundType, Confidence]] = {
    EvidenceKind.OBSERVED: (BoundType.NO_LATER_THAN, Confidence.HIGH),
    EvidenceKind.PLATFORM: (BoundType.EXACT, Confidence.HIGH),
    EvidenceKind.WAYBACK_PAGE: (BoundType.NO_LATER_THAN, Confidence.HIGH),
    EvidenceKind.WAYBACK_IMAGE: (BoundType.NO_LATER_THAN, Confidence.HIGH),
    EvidenceKind.PROVIDER_CRAWL: (BoundType.NO_LATER_THAN, Confidence.MEDIUM),
    EvidenceKind.PAGE_METADATA: (BoundType.CLAIMED, Confidence.MEDIUM),
    EvidenceKind.HTTP_LAST_MODIFIED: (BoundType.CLAIMED, Confidence.LOW),
    EvidenceKind.EXIF: (BoundType.NO_EARLIER_THAN, Confidence.LOW),
    # A trusted C2PA signature is high; callers downgrade it for untrusted signers.
    EvidenceKind.C2PA: (BoundType.NO_EARLIER_THAN, Confidence.HIGH),
}
