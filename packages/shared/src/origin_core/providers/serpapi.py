"""Google Lens and Yandex reverse image search through SerpApi.

Lens: the image is uploaded to SerpApi's Image API (POST /image, at most 500 KB, returns an
image_id valid for about ten minutes) and searched with engine=google_lens, type=exact_matches.
No public URL is needed. Exact-match items give the page link and a thumbnail, not the image
URL, so verification finds the image on the page.

Yandex: engine=yandex_images takes only a public image URL, so it needs a public object store
and is off by default.

Free plan: 250 searches a month, 50 an hour. The upload is metered as a search too until it is
shown not to be (see PLAN.md 1.3), so a Lens query costs two units.

Docs: https://serpapi.com/google-lens-api, https://serpapi.com/google-lens-exact-matches-api,
https://serpapi.com/image-api, https://serpapi.com/yandex-images-api
"""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from PIL import Image

from origin_core.providers.base import AssetRef, CandidateHit, ProviderError, RawResponse

UPLOAD_ENDPOINT = "https://serpapi.com/image"
SEARCH_ENDPOINT = "https://serpapi.com/search.json"
UPLOAD_MAX_BYTES = 500_000

#: SerpApi messages that mean "no results", which is an answer, not a failure.
_NO_RESULTS = re.compile(r"hasn't returned any results|no results", re.IGNORECASE)
_RETRYABLE = re.compile(r"try again|timed out|temporarily", re.IGNORECASE)


def fit_upload(data: bytes, limit: int = UPLOAD_MAX_BYTES) -> bytes:
    """The image as JPEG within the upload limit: unchanged if it fits, else re-encoded smaller.

    The re-encoded copy is still the same picture; it is what SerpApi receives, never what
    ORIGIN stores as evidence.
    """
    if len(data) <= limit:
        return data
    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGB")
    edge = 1600
    for quality in (85, 75, 65, 55, 45):
        copy = image.copy()
        copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        copy.save(out, format="JPEG", quality=quality, optimize=True)
        if out.tell() <= limit:
            return out.getvalue()
        edge = int(edge * 0.8)
    raise ProviderError("could not fit the image under the 500 KB upload limit", retryable=False)


def _raise_for(response: httpx.Response, what: str) -> dict[str, Any]:
    if response.status_code in (429, 500, 502, 503, 504):
        raise ProviderError(f"{what} HTTP {response.status_code}", retryable=True)
    try:
        payload = cast(dict[str, Any], response.json())
    except ValueError as exc:
        raise ProviderError(
            f"{what} returned non-JSON (HTTP {response.status_code})", retryable=False
        ) from exc
    error = payload.get("error")
    if isinstance(error, str) and not _NO_RESULTS.search(error):
        raise ProviderError(f"{what}: {error}", retryable=bool(_RETRYABLE.search(error)))
    if response.status_code >= 400 and not isinstance(error, str):
        raise ProviderError(f"{what} HTTP {response.status_code}", retryable=False)
    return payload


def parse_lens_date(value: object) -> datetime | None:
    """Lens shows dates like "Mar 5, 2024" on some items; anything else is left unparsed."""
    if not isinstance(value, str):
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class LensExactMatches:
    name: str = "lens"
    quota_key: str = "serpapi"
    unit_cost: int = 2  # upload + search, until uploads are shown not to count
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("SerpApi, which queries Google Lens (receives the image bytes)",)

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def params(self) -> dict[str, Any]:
        return {"engine": "google_lens", "type": "exact_matches"}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        upload = fit_upload(subject.data)
        try:
            uploaded = await client.post(
                UPLOAD_ENDPOINT,
                data={"api_key": self._api_key},
                files={"image": ("query.jpg", upload, "image/jpeg")},
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"serpapi upload failed: {exc!r}", retryable=True) from exc
        image_id = _raise_for(uploaded, "serpapi upload").get("image_id")
        if not isinstance(image_id, str):
            raise ProviderError("serpapi upload returned no image_id", retryable=False)
        try:
            response = await client.get(
                SEARCH_ENDPOINT,
                params={**self.params(), "image_id": image_id, "api_key": self._api_key},
                timeout=90,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"lens search failed: {exc!r}", retryable=True) from exc
        _raise_for(response, "lens search")
        return RawResponse(response.content, units=2)

    def parse(self, body: bytes) -> list[CandidateHit]:
        payload = cast(dict[str, Any], json.loads(body))
        hits: list[CandidateHit] = []
        for item in cast(list[dict[str, Any]], payload.get("exact_matches") or []):
            link = item.get("link")
            if not isinstance(link, str):
                continue
            hits.append(
                CandidateHit(
                    page_url=link,
                    image_url=None,  # Lens gives the page and a thumbnail, not the image URL
                    provider_date=parse_lens_date(item.get("date")),
                    rank=int(item.get("position") or len(hits) + 1),
                    title=cast(str | None, item.get("title")),
                    raw={
                        k: item[k]
                        for k in (
                            "source",
                            "thumbnail",
                            "date",
                            "actual_image_width",
                            "actual_image_height",
                        )
                        if k in item
                    },
                )
            )
        return hits


class YandexImages:
    name: str = "yandex"
    quota_key: str = "serpapi"
    unit_cost: int = 1
    requires_public_url: bool = True
    recipients: tuple[str, ...] = (
        "SerpApi, which queries Yandex (receives a short-lived public link to the image)",
    )

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def params(self) -> dict[str, Any]:
        return {"engine": "yandex_images"}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        if subject.public_url is None:
            raise ProviderError("yandex needs a public image URL", retryable=False)
        try:
            response = await client.get(
                SEARCH_ENDPOINT,
                params={**self.params(), "url": subject.public_url, "api_key": self._api_key},
                timeout=90,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"yandex search failed: {exc!r}", retryable=True) from exc
        _raise_for(response, "yandex search")
        return RawResponse(response.content, units=1)

    def parse(self, body: bytes) -> list[CandidateHit]:
        payload = cast(dict[str, Any], json.loads(body))
        hits: list[CandidateHit] = []
        for item in cast(list[dict[str, Any]], payload.get("images_results") or []):
            page, image = item.get("link"), item.get("original")
            if not isinstance(page, str) and not isinstance(image, str):
                continue
            hits.append(
                CandidateHit(
                    page_url=page if isinstance(page, str) else None,
                    image_url=image if isinstance(image, str) else None,
                    rank=int(item.get("position") or len(hits) + 1),
                    title=cast(str | None, item.get("title")),
                    raw={k: item[k] for k in ("source", "thumbnail", "size") if k in item},
                )
            )
        return hits
