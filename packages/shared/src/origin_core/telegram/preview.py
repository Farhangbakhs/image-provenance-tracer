"""Reading Telegram's public channel web preview (t.me/s/<channel>), with no account.

Any browser can open a public channel's preview: 20 posts a page, older pages through
`?before=<message id>`, and search through `?q=<words>`. A single post's own page,
`t.me/<channel>/<id>`, carries its photo as og:image; the `?embed=1` form carries the same
widget as the channel page, with the post time.

The markup was checked against live pages on 2026-11-11: each post is a
`div.tgme_widget_message` with `data-post="<channel>/<id>"`, its time in
`a.tgme_widget_message_date > time[datetime]`, photos as `a.tgme_widget_message_photo_wrap`
with the image URL in a `background-image` style, and forwards as
`.tgme_widget_message_forwarded_from`, linking the original post when it is public.

Preview HTML is untrusted input: parsed, never executed, and its text is data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import lxml.html

_html: Any = lxml.html

#: Public channel usernames: 5-32 characters, letters, digits and underscores.
CHANNEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
_POST_PATH = re.compile(r"^/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})/(\d+)/?$")
_BACKGROUND = re.compile(r"background-image:\s*url\(['\"]?([^'\")]+)['\"]?\)")
_TELEGRAM_HOSTS = frozenset({"t.me", "telegram.me", "www.t.me", "www.telegram.me"})


class NotAChannel(ValueError):
    """The text is not a public channel username."""


def channel_name(text: str) -> str:
    """A channel username from `name`, `@name`, `t.me/name` or `https://t.me/s/name`."""
    value = text.strip()
    if "://" in value or value.startswith(("t.me/", "telegram.me/")):
        parts = urlsplit(value if "://" in value else f"https://{value}")
        if (parts.hostname or "") not in _TELEGRAM_HOSTS:
            raise NotAChannel(f"not a Telegram link: {text!r}")
        segments = [s for s in parts.path.split("/") if s]
        if segments[:1] == ["s"]:
            segments = segments[1:]
        value = segments[0] if segments else ""
    value = value.removeprefix("@")
    if not CHANNEL.match(value):
        raise NotAChannel(f"not a public channel username: {text!r}")
    return value


def post_url(channel: str, message_id: int) -> str:
    return f"https://t.me/{channel}/{message_id}"


def embed_url(channel: str, message_id: int) -> str:
    return f"https://t.me/{channel}/{message_id}?embed=1"


def channel_page_url(channel: str, *, before: int | None = None, query: str | None = None) -> str:
    params: dict[str, str] = {}
    if before is not None:
        params["before"] = str(before)
    if query:
        params["q"] = query
    suffix = f"?{urlencode(params)}" if params else ""
    return f"https://t.me/s/{channel}{suffix}"


def parse_post_url(url: str) -> tuple[str, int] | None:
    """(channel, message id) for a t.me post link, or None for anything else."""
    parts = urlsplit(url)
    if (parts.hostname or "") not in _TELEGRAM_HOSTS:
        return None
    match = _POST_PATH.match(parts.path)
    return (match.group(1), int(match.group(2))) if match else None


@dataclass(frozen=True)
class Forward:
    """Where a post says it was forwarded from. The link is absent for hidden senders."""

    name: str | None
    channel: str | None = None
    message_id: int | None = None


@dataclass(frozen=True)
class PreviewPost:
    channel: str
    message_id: int
    posted_at: datetime | None
    text: str
    photos: list[str] = field(default_factory=list[str])
    forwarded_from: Forward | None = None

    @property
    def url(self) -> str:
        return post_url(self.channel, self.message_id)


@dataclass(frozen=True)
class PreviewPage:
    posts: list[PreviewPost]
    #: The `before` value that loads the next older page, if there is one.
    older: int | None


def _text(node: Any) -> str:
    for br in node.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    return " ".join(node.text_content().split())


def _forward(node: Any) -> Forward | None:
    found = node.xpath(".//*[contains(@class,'tgme_widget_message_forwarded_from')]")
    if not found:
        return None
    block = found[0]
    names = block.xpath(".//*[contains(@class,'tgme_widget_message_forwarded_from_name')]")
    name = _text(names[0]) if names else None
    links = block.xpath(".//a[@href]")
    if links:
        target = parse_post_url(links[0].get("href"))
        if target:
            return Forward(name or None, target[0], target[1])
        try:
            return Forward(name or None, channel_name(links[0].get("href")))
        except NotAChannel:
            pass
    return Forward(name or None)


def _post(node: Any) -> PreviewPost | None:
    ident = node.get("data-post") or ""
    channel, _, number = ident.partition("/")
    if not (CHANNEL.match(channel) and number.isdigit()):
        return None
    times = node.xpath(".//a[contains(@class,'tgme_widget_message_date')]//time[@datetime]")
    posted_at: datetime | None = None
    if times:
        try:
            posted_at = datetime.fromisoformat(times[0].get("datetime"))
        except ValueError:
            posted_at = None
    photos: list[str] = []
    for wrap in node.xpath(".//a[contains(@class,'tgme_widget_message_photo_wrap')]"):
        match = _BACKGROUND.search(wrap.get("style") or "")
        if match and match.group(1).startswith("https://"):
            photos.append(match.group(1))
    texts = node.xpath(".//div[contains(@class,'tgme_widget_message_text')]")
    return PreviewPost(
        channel=channel,
        message_id=int(number),
        posted_at=posted_at,
        text=_text(texts[0]) if texts else "",
        photos=photos,
        forwarded_from=_forward(node),
    )


def parse_preview(body: bytes) -> PreviewPage:
    """Every post on a channel preview page (or a single post's embed page), oldest first."""
    if not body.strip():
        return PreviewPage([], None)
    doc = _html.fromstring(body)
    posts = [
        post
        for node in doc.xpath("//div[contains(@class,'tgme_widget_message') and @data-post]")
        if (post := _post(node)) is not None
    ]
    older: int | None = None
    more = doc.xpath("//*[contains(@class,'tme_messages_more') and @data-before]")
    if more and str(more[0].get("data-before")).isdigit():
        older = int(more[0].get("data-before"))
    posts.sort(key=lambda p: p.message_id)
    return PreviewPage(posts, older)
