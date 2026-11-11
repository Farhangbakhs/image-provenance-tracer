"""Telegram public preview: channel names, post links and the t.me/s page parser.

SYNTHETIC: the HTML below is hand-written to the markup of live t.me/s pages as checked on
2026-11-11 (see origin_core.telegram.preview), with invented channels and text.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from origin_core.telegram.preview import (
    Forward,
    NotAChannel,
    channel_name,
    channel_page_url,
    embed_url,
    parse_post_url,
    parse_preview,
    post_url,
)

PAGE = b"""<!DOCTYPE html><html><head>
<meta property="og:image" content="https://cdn4.telesco.pe/file/avatar.jpg">
<link rel="prev" href="/s/demo_wire?before=101"></head><body>
<section class="tgme_channel_history js-message_history">
<div class="tme_messages_more js-messages_more" data-before="101"></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message text_not_supported_wrap js-widget_message"
      data-post="demo_wire/102">
  <div class="tgme_widget_message_bubble">
   <div class="tgme_widget_message_forwarded_from accent_color">Forwarded from&nbsp;<a
     class="tgme_widget_message_forwarded_from_name" href="https://t.me/first_hand/7"><span
     dir="auto">First Hand</span></a></div>
   <a class="tgme_widget_message_photo_wrap 1 2" href="https://t.me/demo_wire/102"
      style="width:800px;background-image:url('https://cdn4.telesco.pe/file/photo-102.jpg')">
    <div class="tgme_widget_message_photo" style="padding-top:75%"></div></a>
   <div class="tgme_widget_message_text js-message_text" dir="auto">Water in the street<br/>
    this morning</div>
   <div class="tgme_widget_message_footer"><span class="tgme_widget_message_meta">
    <a class="tgme_widget_message_date" href="https://t.me/demo_wire/102"><time
     datetime="2024-10-29T18:02:11+00:00" class="time">18:02</time></a></span></div>
  </div></div></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap">
 <div class="tgme_widget_message js-widget_message" data-post="demo_wire/103">
  <div class="tgme_widget_message_forwarded_from accent_color">Forwarded from&nbsp;<span
    class="tgme_widget_message_forwarded_from_name"><span
    dir="auto">Hidden Person</span></span></div>
  <div class="tgme_widget_message_text js-message_text" dir="auto">Text only</div>
  <a class="tgme_widget_message_date" href="https://t.me/demo_wire/103"><time
   datetime="2024-10-30T08:00:00+00:00">08:00</time></a>
 </div></div>
<div class="tgme_widget_message js-widget_message" data-post="not a post"></div>
</section></body></html>"""


def test_channel_name_accepts_the_usual_forms() -> None:
    for text in ("demo_wire", "@demo_wire", "t.me/demo_wire", "https://t.me/s/demo_wire/"):
        assert channel_name(text) == "demo_wire"
    assert channel_name("https://t.me/demo_wire/55") == "demo_wire"


@pytest.mark.parametrize(
    "text", ["", "abc", "1channel", "https://example.com/demo_wire", "t.me/+invitehash"]
)
def test_channel_name_rejects_the_rest(text: str) -> None:
    with pytest.raises(NotAChannel):
        channel_name(text)


def test_urls() -> None:
    assert post_url("demo_wire", 5) == "https://t.me/demo_wire/5"
    assert embed_url("demo_wire", 5) == "https://t.me/demo_wire/5?embed=1"
    assert channel_page_url("demo_wire") == "https://t.me/s/demo_wire"
    assert (
        channel_page_url("demo_wire", before=90, query="flood street")
        == "https://t.me/s/demo_wire?before=90&q=flood+street"
    )
    assert parse_post_url("https://t.me/demo_wire/5") == ("demo_wire", 5)
    assert parse_post_url("https://t.me/s/demo_wire/5") == ("demo_wire", 5)
    assert parse_post_url("https://t.me/demo_wire") is None
    assert parse_post_url("https://example.com/demo_wire/5") is None


def test_parse_preview_reads_posts_photos_times_and_forwards() -> None:
    page = parse_preview(PAGE)
    assert page.older == 101
    first, second = page.posts
    assert first.url == "https://t.me/demo_wire/102"
    assert first.posted_at == datetime(2024, 10, 29, 18, 2, 11, tzinfo=UTC)
    assert first.photos == ["https://cdn4.telesco.pe/file/photo-102.jpg"]
    assert first.text == "Water in the street this morning"
    assert first.forwarded_from == Forward("First Hand", "first_hand", 7)
    assert second.photos == []
    assert second.forwarded_from == Forward("Hidden Person")


def test_parse_preview_of_nothing() -> None:
    assert parse_preview(b"").posts == []
    assert parse_preview(b"<html><body>no posts</body></html>").older is None
