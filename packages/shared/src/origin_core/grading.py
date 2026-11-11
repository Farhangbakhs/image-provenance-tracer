"""Admiralty-scale grading: source reliability (A-F) and information credibility (1-6).

Reliability belongs to the publisher (a domain or channel) and comes from the `sources` table.
Without an analyst's assessment a source is graded F, "reliability cannot be judged": ORIGIN does
not invent reputations.

Credibility belongs to one sighting's information, "this copy existed by this date, and it is
this picture", and is computed from the evidence:

  1 confirmed         same picture, and two or more independent proofs of the date
  2 probably true     same picture, and one independent proof
  3 possibly true     an edited copy with a proof, or the same picture dated only by claims
  4 doubtful          dated only by ORIGIN's own observation or weak claims
  5 improbable        the page's own date contradicts the proven bounds
  6 cannot be judged  no dating evidence at all

An independent proof is a high-confidence platform timestamp, archive capture or trusted C2PA
signature. ORIGIN's own fetch proves only that the copy exists now, so it is not counted.
"""

from __future__ import annotations

from dataclasses import dataclass

from origin_core.enums import BoundType, Confidence, EvidenceKind, MatchClass

RULE_VERSION = "grading.v1"

PROOF_KINDS = {
    EvidenceKind.PLATFORM,
    EvidenceKind.WAYBACK_PAGE,
    EvidenceKind.WAYBACK_IMAGE,
    EvidenceKind.C2PA,
}
UNGRADED_RATIONALE = (
    "No reliability assessment is recorded for this source, so it is graded F "
    "(reliability cannot be judged) until an analyst sets one."
)


@dataclass(frozen=True)
class EvidenceFact:
    kind: EvidenceKind
    bound: BoundType
    confidence: Confidence


@dataclass(frozen=True)
class Credibility:
    grade: int
    rationale: str


def credibility(
    match_class: MatchClass, evidence: list[EvidenceFact], *, contradicted: bool
) -> Credibility:
    proofs = sorted(
        {
            e.kind.value
            for e in evidence
            if e.kind in PROOF_KINDS and e.confidence is Confidence.HIGH
        }
    )
    claims = [e for e in evidence if e.bound is BoundType.CLAIMED]
    same_picture = match_class in (MatchClass.EXACT, MatchClass.NEAR_DUPLICATE)
    picture = "the same picture" if same_picture else "an edited copy"

    if not evidence:
        return Credibility(6, "No dating evidence was found for this sighting.")
    if contradicted:
        return Credibility(
            5, "The page's own date contradicts the proven bounds; see the date notes."
        )
    if same_picture and len(proofs) >= 2:
        return Credibility(
            1, f"{picture}, dated by {len(proofs)} independent proofs ({', '.join(proofs)})."
        )
    if same_picture and len(proofs) == 1:
        return Credibility(2, f"{picture}, dated by one independent proof ({proofs[0]}).")
    if proofs:
        return Credibility(3, f"{picture}, dated by {', '.join(proofs)}.")
    if same_picture and any(c.confidence is not Confidence.LOW for c in claims):
        kinds = ", ".join(sorted({c.kind.value for c in claims}))
        return Credibility(3, f"{picture}, dated only by claims ({kinds}).")
    return Credibility(4, f"{picture}, dated only by ORIGIN's own observation or weak claims.")
