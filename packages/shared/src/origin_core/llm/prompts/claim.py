"""claim.v1: what one page claims its copy of the image shows.

Output is validated twice: by schema, and by checking that the quote the model cites is a
verbatim excerpt of the text it was given. A claim whose quote cannot be found is rejected and
asked for again, so every stored claim points at real words on a real page.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from origin_core.llm.base import UNTRUSTED_RULES, Prompt, untrusted_block

VERSION = "claim.v1"

SYSTEM = f"""You help an open-source intelligence analyst trace where a photograph has appeared.
You are given the text around ONE copy of the photograph on ONE web page. Report what that text
claims the photograph shows.

Rules:
- Report only what the text states or clearly implies about this photograph. If it makes no
  claim about the photograph, set has_claim to false and leave the other fields null.
- event: what happened, in a few words. place: where, as stated. date_text: when, exactly as
  stated. date_iso: that date as YYYY-MM-DD only if the text makes the day unambiguous, else null.
- actor_role: who is involved, as roles or groups only ("police", "protesters", "a reporter").
  Never output a person's name, and never try to identify anyone shown in the photograph.
- stance: "asserts" if the text presents the claim as true, "disputes" if it says the claim is
  false or the photo is miscaptioned, "mentions" if it only reports that others claim it.
- quote: one short verbatim excerpt (at most 300 characters) from the given text that carries
  the claim, copied character for character. Do not paraphrase, translate or fix it.
- language: the quote's ISO 639-1 code. translation: an English translation of the quote if it
  is not English, else null.
- {UNTRUSTED_RULES}
"""


class ClaimOut(BaseModel):
    has_claim: bool
    event: str | None = None
    place: str | None = None
    date_text: str | None = None
    date_iso: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    actor_role: str | None = None
    stance: Literal["asserts", "disputes", "mentions"] | None = None
    quote: str | None = Field(default=None, max_length=400)
    language: str | None = None
    translation: str | None = None


SCHEMA = ClaimOut.model_json_schema()


@dataclass(frozen=True)
class ClaimSource:
    """The exact text shown to the model; quote offsets are positions in `text`."""

    text: str


def build_source(title: str | None, caption: str | None, body: str | None) -> ClaimSource:
    parts = [
        f"Title: {title}" if title else None,
        f"Caption: {caption}" if caption else None,
        f"Text: {body}" if body else None,
    ]
    return ClaimSource("\n".join(p for p in parts if p))


def build_prompt(label: str, domain: str, source: ClaimSource) -> Prompt:
    user = (
        f"The photograph appears on {domain}. Here is the text from that page:\n\n"
        f"{untrusted_block(label, source.text)}\n\n"
        "What does this text claim the photograph shows?"
    )
    return Prompt(version=VERSION, system=SYSTEM, user=user, schema=SCHEMA)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def locate_quote(source: ClaimSource, quote: str) -> tuple[int, int] | None:
    """Start and end of `quote` in the source text, tolerant only of whitespace differences."""
    exact = source.text.find(quote)
    if exact >= 0:
        return exact, exact + len(quote)
    words = _normalise(quote).split(" ")
    if not words or not words[0]:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, source.text)
    return (match.start(), match.end()) if match else None


def check(source: ClaimSource) -> Callable[[ClaimOut], str | None]:
    """A validator for LLMRunner.complete_validated."""

    def validate(out: ClaimOut) -> str | None:
        if not out.has_claim:
            return None
        if not out.quote:
            return "has_claim is true but no quote was given"
        if locate_quote(source, out.quote) is None:
            return (
                "the quote is not a verbatim excerpt of the given text; copy the exact words "
                f"from the text (got: {out.quote[:120]!r})"
            )
        return None

    return validate
