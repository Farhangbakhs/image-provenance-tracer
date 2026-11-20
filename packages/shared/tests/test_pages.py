from __future__ import annotations

from datetime import UTC, datetime

from origin_core.pages import MAX_IMAGES, page_text, parse_page

ARTICLE = b"""<!doctype html><html><head>
<title>Fallback title</title>
<meta property="og:title" content="Floods hit the city centre">
<meta property="og:image" content="/media/flood-large.jpg">
<meta property="article:published_time" content="2024-03-05T14:20:00+02:00">
<script type="application/ld+json">{"@type": "NewsArticle", "datePublished": "2024-01-01"}</script>
</head><body>
<img src="/static/logo.png" width="32" height="32">
<img src="photo-small.jpg" srcset="photo-small.jpg 480w, photo-big.jpg 1600w">
<img data-src="https://cdn.example/lazy.webp">
<img src="data:image/png;base64,AAAA">
<img src="/icons/share.svg">
<script>document.write('<img src="https://evil.example/x.jpg">')</script>
</body></html>"""


def test_title_images_and_published_date() -> None:
    page = parse_page("https://news.example/2024/floods", ARTICLE)
    assert page.title == "Floods hit the city centre"
    assert page.images == [
        "https://news.example/media/flood-large.jpg",
        "https://news.example/2024/photo-big.jpg",
        "https://news.example/2024/photo-small.jpg",
        "https://cdn.example/lazy.webp",
    ]
    assert page.published is not None
    assert page.published.value == datetime(2024, 3, 5, 12, 20, tzinfo=UTC)
    assert page.published.source == "meta:article:published_time"
    assert page.published.day_only is False


def test_json_ld_date_when_no_meta() -> None:
    body = b"""<html><head><script type="application/ld+json">
    [{"@type": "WebPage", "mainEntity": {"@type": "Article", "datePublished": "2023-07-14"}}]
    </script></head><body><p>text</p></body></html>"""
    page = parse_page("https://blog.example/p", body)
    assert page.published is not None
    assert page.published.value == datetime(2023, 7, 14, tzinfo=UTC)
    assert (page.published.source, page.published.day_only) == ("json-ld", True)


def test_no_date_and_garbage_are_handled() -> None:
    assert (
        parse_page("https://x.example/", b"<html><body>no date here</body></html>").published
        is None
    )
    assert parse_page("https://x.example/", b"").images == []


def test_image_list_is_capped() -> None:
    body = (
        b"<html><body>"
        + b"".join(f'<img src="/i{n}.jpg">'.encode() for n in range(40))
        + b"</body></html>"
    )
    assert len(parse_page("https://x.example/", body).images) == MAX_IMAGES


SOCIAL = b"""<!doctype html><html><head>
<title>Instagram</title>
<meta property="og:title" content="Irish Examiner on Instagram: &quot;Our front page&quot;">
<meta property="og:description" content="  12 likes, 3 comments - irishexaminer on March 4, 2026:
&quot;Our front page today: a strike on a school in Minab.&quot;  ">
<meta name="description" content="Instagram">
<meta property="og:image" content="https://cdn.example/post.jpg">
</head><body>Log in to continue</body></html>"""


def test_social_page_keeps_its_og_title_and_description() -> None:
    page = parse_page("https://www.instagram.com/p/abc/", SOCIAL)
    assert page.title == 'Irish Examiner on Instagram: "Our front page"'
    # Whitespace is collapsed, and og:description wins over the generic meta description.
    assert page.description == (
        '12 likes, 3 comments - irishexaminer on March 4, 2026: "Our front page today: a strike on '
        'a school in Minab."'
    )


def test_description_falls_back_through_twitter_then_meta() -> None:
    twitter = b'<html><head><meta name="twitter:description" content="A tweet"></head></html>'
    plain = b'<html><head><meta name="description" content="A summary"></head></html>'
    assert parse_page("https://x.example/", twitter).description == "A tweet"
    assert parse_page("https://x.example/", plain).description == "A summary"
    assert parse_page("https://x.example/", b"<html><head></head></html>").description is None


def test_page_text_uses_the_description_when_the_body_is_a_wall() -> None:
    page = parse_page("https://www.instagram.com/p/abc/", SOCIAL)
    assert page.description is not None
    assert page_text(page, None) == page.description
    # A login-wall body is boilerplate; the post text is added to it, not lost.
    assert page.description in (page_text(page, "Log in to continue") or "")
    # A real article body is left alone.
    article = "A full article about the strike. " * 10
    assert page_text(page, article) == article
    # No description: the extracted body is all there is.
    assert page_text(parse_page("https://x.example/", b"<html></html>"), None) is None
