"""A claim can be read from a social post whose body is a login wall."""

from __future__ import annotations

from origin_core.llm.prompts import claim as claim_prompt
from origin_worker.branch import _read_page  # pyright: ignore[reportPrivateUsage]

INSTAGRAM = b"""<!doctype html><html><head><title>Instagram</title>
<meta property="og:title" content="Irish Examiner on Instagram: Our front page">
<meta property="og:description" content="Our front page today: a strike on a school in Minab.">
<meta property="og:image" content="https://cdn.example/post.jpg">
</head><body><div>Log in to see more</div></body></html>"""


def test_the_claim_is_read_from_og_title_and_description() -> None:
    page, caption, text = _read_page(
        "https://www.instagram.com/p/abc/", INSTAGRAM, "https://cdn.example/post.jpg"
    )
    source = claim_prompt.build_source(page.title, caption, text)

    assert "Title: Irish Examiner on Instagram: Our front page" in source.text
    assert "a strike on a school in Minab" in source.text
    # The quote check works on the fallback text exactly as on an article body.
    span = claim_prompt.locate_quote(source, "a strike on a school in Minab")
    assert span is not None
    assert source.text[span[0] : span[1]] == "a strike on a school in Minab"
