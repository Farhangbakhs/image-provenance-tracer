"""Google Cloud Vision web detection: pages and images on the web that match the query.

Sends the image bytes (no public URL needed). Free for the first 1,000 units a month; the
quota policy stops at 950 so a miscount cannot reach a charge.

Docs: https://docs.cloud.google.com/vision/docs/detecting-web
Response: webDetection.{fullMatchingImages, partialMatchingImages, pagesWithMatchingImages
{url, pageTitle, fullMatchingImages, partialMatchingImages}, visuallySimilarImages, ...}.
Visually similar images are not used: they are different pictures by design.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import httpx

from origin_core.providers.base import AssetRef, CandidateHit, ProviderError, RawResponse

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
MAX_RESULTS = 50


class VisionWebDetection:
    name: str = "vision"
    quota_key: str = "vision"
    unit_cost: int = 1
    requires_public_url: bool = False
    recipients: tuple[str, ...] = ("Google Cloud Vision (receives the image bytes)",)

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def params(self) -> dict[str, Any]:
        return {"feature": "WEB_DETECTION", "maxResults": MAX_RESULTS}

    async def fetch(self, subject: AssetRef, client: httpx.AsyncClient) -> RawResponse:
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(subject.data).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION", "maxResults": MAX_RESULTS}],
                }
            ]
        }
        try:
            response = await client.post(
                ENDPOINT, params={"key": self._api_key}, json=body, timeout=60
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"vision request failed: {exc!r}", retryable=True) from exc
        if response.status_code in (429, 500, 502, 503, 504):
            raise ProviderError(f"vision HTTP {response.status_code}", retryable=True)
        if response.status_code != 200:
            raise ProviderError(
                f"vision HTTP {response.status_code}: {response.text[:300]}", retryable=False
            )
        return RawResponse(response.content, units=1)

    def parse(self, body: bytes) -> list[CandidateHit]:
        data = cast(dict[str, Any], json.loads(body))
        responses = cast(list[dict[str, Any]], data.get("responses") or [{}])
        first = responses[0]
        if "error" in first:
            raise ProviderError(f"vision error: {first['error']}", retryable=False)
        web = cast(dict[str, Any], first.get("webDetection") or {})

        hits: list[CandidateHit] = []
        seen: set[tuple[str | None, str | None]] = set()

        def add(page: str | None, image: str | None, title: str | None, kind: str) -> None:
            if (page, image) in seen or not (page or image):
                return
            seen.add((page, image))
            hits.append(
                CandidateHit(
                    page_url=page,
                    image_url=image,
                    title=title,
                    rank=len(hits) + 1,
                    raw={"match": kind},
                )
            )

        for page in cast(list[dict[str, Any]], web.get("pagesWithMatchingImages") or []):
            url = cast(str | None, page.get("url"))
            title = cast(str | None, page.get("pageTitle"))
            images: list[tuple[str, str]] = []
            for kind, key in (("full", "fullMatchingImages"), ("partial", "partialMatchingImages")):
                for item in cast(list[dict[str, Any]], page.get(key) or []):
                    if "url" in item:
                        images.append((kind, str(item["url"])))
            if not images:
                add(url, None, title, "page")
            for kind, image in images:
                add(url, image, title, kind)
        for kind in ("full", "partial"):
            key = "fullMatchingImages" if kind == "full" else "partialMatchingImages"
            for image in cast(list[dict[str, Any]], web.get(key) or []):
                if "url" in image:
                    add(None, cast(str, image["url"]), None, kind)
        return hits
