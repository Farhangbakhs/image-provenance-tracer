"""narrative.v1: group claims into narratives and say which ones contradict the earliest.

Claims are given short ids (c1, c2, ...) in order of each sighting's proven date. The model must
assign every id to exactly one narrative and may cite no id that was not given; output that
breaks either rule is rejected and asked for again. Which narrative is the root, and where each
branch diverges, is then decided from the evidence, not by the model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from origin_core.llm.base import UNTRUSTED_RULES, Prompt, untrusted_block

VERSION = "narrative.v1"

SYSTEM = f"""You help an open-source intelligence analyst see how the story told about one
photograph changed as it spread. You are given the claims different web pages make about the
same photograph, in the order the pages are proven to have existed (earliest first).

Group the claims into narratives. Claims belong to the same narrative when they agree on what
the photograph shows: the same event, the same place and the same time, allowing for wording,
language and level of detail. Claims that place the photograph at a different event, place or
time belong to a different narrative, even if each is internally consistent.

Rules:
- Use only the claim ids you are given, and put every id in exactly one narrative.
- label: a short neutral description of the narrative ("Flood in Valencia, Oct 2024").
- contradicts_earliest: true if this narrative disagrees with the narrative containing c1 on
  event, place or date; then name the dimension in contradiction and explain in reason.
- Do not judge which narrative is true, and never identify people.
- {UNTRUSTED_RULES}
"""


class NarrativeOut(BaseModel):
    label: str = Field(max_length=120)
    summary: str = Field(max_length=400)
    claim_ids: list[str] = Field(min_length=1)
    contradicts_earliest: bool
    contradiction: Literal["event", "place", "date"] | None = None
    reason: str | None = Field(default=None, max_length=400)


class NarrativesOut(BaseModel):
    narratives: list[NarrativeOut] = Field(min_length=1)


SCHEMA = NarrativesOut.model_json_schema()


@dataclass(frozen=True)
class ClaimLine:
    alias: str
    seen: str
    event: str | None
    place: str | None
    date_text: str | None
    stance: str | None
    quote: str


def build_prompt(lines: list[ClaimLine]) -> Prompt:
    rows = [
        {
            "id": line.alias,
            "page_proven_by": line.seen,
            "event": line.event,
            "place": line.place,
            "date_as_stated": line.date_text,
            "stance": line.stance,
            "quote": line.quote,
        }
        for line in lines
    ]
    user = (
        "Claims about the same photograph, earliest first. Fields other than id and "
        "page_proven_by were extracted from web pages:\n\n"
        f"{untrusted_block('claims', json.dumps(rows, ensure_ascii=False, indent=1))}\n\n"
        "Group them into narratives."
    )
    return Prompt(version=VERSION, system=SYSTEM, user=user, schema=SCHEMA)


def check(aliases: list[str]) -> Callable[[NarrativesOut], str | None]:
    """Every given id exactly once; no invented ids."""

    def validate(out: NarrativesOut) -> str | None:
        cited = [cid for n in out.narratives for cid in n.claim_ids]
        unknown = sorted(set(cited) - set(aliases))
        if unknown:
            return f"cited claim ids that were not given: {unknown}"
        duplicated = sorted({cid for cid in cited if cited.count(cid) > 1})
        if duplicated:
            return f"claim ids placed in more than one narrative: {duplicated}"
        missing = [a for a in aliases if a not in cited]
        if missing:
            return f"claim ids not placed in any narrative: {missing}"
        return None

    return validate
