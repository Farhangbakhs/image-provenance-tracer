"""Google's own redirect, consent and captcha pages are recognised; publishers on Google are not."""

from __future__ import annotations

import pytest

from origin_core.redirects import google_block


@pytest.mark.parametrize(
    ("url", "where"),
    [
        ("https://www.google.com/sorry/index?continue=x", "www.google.com/sorry/index"),
        ("https://www.google.com/goto?url=abc", "www.google.com/goto"),
        ("https://www.google.com/url?q=https://x.example", "www.google.com/url"),
        ("https://www.google.co.uk/search?q=a", "www.google.co.uk/search"),
        ("https://consent.google.com/ml?continue=x", "consent.google.com/ml"),
        ("https://consent.youtube.com/m?continue=x", "consent.youtube.com/m"),
        ("https://accounts.google.com/signin", "accounts.google.com/signin"),
    ],
)
def test_google_gate_pages_are_blocked(url: str, where: str) -> None:
    assert google_block(url) == where


@pytest.mark.parametrize(
    "url",
    [
        "https://news.example/story",
        "https://sites.google.com/view/a-report",  # a publisher that lives on a Google host
        "https://www.google.com/maps/place/x",
        "https://notgoogle.com/goto?url=x",  # only Google's own domains count
        "https://google.com.evil.example/sorry",
    ],
)
def test_other_pages_are_not(url: str) -> None:
    assert google_block(url) is None
