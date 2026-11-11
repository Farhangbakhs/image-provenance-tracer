from __future__ import annotations

from origin_core.enums import BoundType, Confidence, EvidenceKind, MatchClass
from origin_core.grading import EvidenceFact, credibility

OBSERVED = EvidenceFact(EvidenceKind.OBSERVED, BoundType.NO_LATER_THAN, Confidence.HIGH)
ARCHIVE = EvidenceFact(EvidenceKind.WAYBACK_PAGE, BoundType.NO_LATER_THAN, Confidence.HIGH)
PLATFORM = EvidenceFact(EvidenceKind.PLATFORM, BoundType.EXACT, Confidence.HIGH)
PUBLISHED = EvidenceFact(EvidenceKind.PAGE_METADATA, BoundType.CLAIMED, Confidence.MEDIUM)
LAST_MODIFIED = EvidenceFact(EvidenceKind.HTTP_LAST_MODIFIED, BoundType.CLAIMED, Confidence.LOW)
UNTRUSTED_C2PA = EvidenceFact(EvidenceKind.C2PA, BoundType.NO_EARLIER_THAN, Confidence.LOW)

NEAR = MatchClass.NEAR_DUPLICATE
DERIVED = MatchClass.DERIVATIVE


def test_grades() -> None:
    assert credibility(NEAR, [OBSERVED, ARCHIVE, PLATFORM], contradicted=False).grade == 1
    assert credibility(NEAR, [OBSERVED, ARCHIVE], contradicted=False).grade == 2
    assert credibility(DERIVED, [OBSERVED, ARCHIVE], contradicted=False).grade == 3
    assert credibility(NEAR, [OBSERVED, PUBLISHED], contradicted=False).grade == 3
    assert credibility(NEAR, [OBSERVED, LAST_MODIFIED], contradicted=False).grade == 4
    assert credibility(NEAR, [OBSERVED, ARCHIVE], contradicted=True).grade == 5
    assert credibility(NEAR, [], contradicted=False).grade == 6


def test_our_own_fetch_and_untrusted_signatures_are_not_proofs() -> None:
    result = credibility(MatchClass.EXACT, [OBSERVED, UNTRUSTED_C2PA], contradicted=False)
    assert result.grade == 4
    assert "ORIGIN's own observation" in result.rationale


def test_rationale_names_the_proofs() -> None:
    result = credibility(NEAR, [OBSERVED, ARCHIVE, PLATFORM], contradicted=False)
    assert "platform" in result.rationale and "wayback_page" in result.rationale
