"""Recognising a search engine's own pages where a result's publisher page should have been.

Lens links are google.com redirects. A fetch that is followed all the way ends on the
publisher's page. When it ends on Google's own redirect notice, consent or captcha page instead,
that page has no picture on it, and calling the result "no image on the page" would blame the
publisher for something Google did. Those hits are reported as blocked by the Google redirect.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# google.com, google.co.uk, google.com.au, google.de: Google's own domains, and nothing that
# merely starts with them (google.com.evil.example).
_GOOGLE = re.compile(r"(^|\.)google\.(com(\.[a-z]{2})?|co\.[a-z]{2}|[a-z]{2,3})$")
#: Hosts that only ever show a gate (consent, sign-in), never a publisher's content.
_GATE_HOSTS = frozenset({"consent.google.com", "accounts.google.com", "consent.youtube.com"})
#: Paths on Google's own hosts that redirect, challenge or search; none is a publisher page.
_WRAPPER_PATHS = ("/goto", "/url", "/sorry", "/search", "/interstitial", "/imgres")


def google_block(final_url: str) -> str | None:
    """Where a fetch stopped on a Google redirect, consent or captcha page, else None.

    A publisher that happens to live on a Google host (sites.google.com/view/...) is not blocked.
    """
    parts = urlsplit(final_url)
    host = (parts.hostname or "").lower()
    if not (_GOOGLE.search(host) or host in _GATE_HOSTS):
        return None
    if host in _GATE_HOSTS or parts.path.startswith(_WRAPPER_PATHS):
        return f"{host}{parts.path}"
    return None
