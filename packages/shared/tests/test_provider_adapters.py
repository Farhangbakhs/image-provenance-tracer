"""Vision, Lens and Yandex adapters: request shape, parsing and error mapping.

SYNTHETIC: the response bodies here are hand-written to the shapes documented by Google and
SerpApi (see each adapter's module docstring). They are replaced by contract tests against real
recordings once API keys are available; until then they pin the parsing to the documentation.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime

import httpx
import pytest
from PIL import Image

from origin_core.providers.base import AssetRef, ProviderError
from origin_core.providers.serpapi import (
    UPLOAD_MAX_BYTES,
    LensExactMatches,
    YandexImages,
    fit_upload,
    parse_lens_date,
)
from origin_core.providers.vision import VisionWebDetection


def _asset(data: bytes = b"\xff\xd8\xffjpeg", public_url: str | None = None) -> AssetRef:
    return AssetRef(
        id="a",
        sha256="0" * 64,
        content_type="image/jpeg",
        data=data,
        width=1,
        height=1,
        public_url=public_url,
    )


VISION_BODY = {
    "responses": [
        {
            "webDetection": {
                "pagesWithMatchingImages": [
                    {
                        "url": "https://news.example/story",
                        "pageTitle": "Flooding in the city",
                        "fullMatchingImages": [{"url": "https://news.example/img/flood.jpg"}],
                    },
                    {"url": "https://blog.example/post", "pageTitle": "Repost"},
                ],
                "fullMatchingImages": [
                    {"url": "https://news.example/img/flood.jpg"},
                    {"url": "https://cdn.example/f.jpg"},
                ],
                "partialMatchingImages": [{"url": "https://cdn.example/crop.jpg"}],
                "visuallySimilarImages": [{"url": "https://other.example/similar.jpg"}],
            }
        }
    ]
}


def test_vision_parses_pages_and_images_without_similar_images() -> None:
    hits = VisionWebDetection("k").parse(json.dumps(VISION_BODY).encode())
    pairs = [(h.page_url, h.image_url, h.raw["match"]) for h in hits]
    assert pairs == [
        ("https://news.example/story", "https://news.example/img/flood.jpg", "full"),
        ("https://blog.example/post", None, "page"),
        (None, "https://news.example/img/flood.jpg", "full"),
        (None, "https://cdn.example/f.jpg", "full"),
        (None, "https://cdn.example/crop.jpg", "partial"),
    ]
    assert hits[0].title == "Flooding in the city"
    assert all("similar" not in (h.image_url or "") for h in hits)


def test_vision_reports_per_request_errors() -> None:
    body = {"responses": [{"error": {"code": 3, "message": "Bad image data."}}]}
    with pytest.raises(ProviderError, match="Bad image data"):
        VisionWebDetection("k").parse(json.dumps(body).encode())


async def test_vision_sends_bytes_and_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"responses": [{}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        raw = await VisionWebDetection("secret-key").fetch(_asset(), client)
    [request] = seen
    assert request.url.params["key"] == "secret-key"
    sent = json.loads(request.content)["requests"][0]
    assert base64.b64decode(sent["image"]["content"]) == b"\xff\xd8\xffjpeg"
    assert sent["features"][0]["type"] == "WEB_DETECTION"
    assert raw.units == 1


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (403, False)])
async def test_vision_maps_http_errors(status: int, retryable: bool) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status))
    ) as client:
        with pytest.raises(ProviderError) as exc:
            await VisionWebDetection("k").fetch(_asset(), client)
    assert exc.value.retryable is retryable


LENS_BODY = {
    "search_metadata": {"status": "Success"},
    "exact_matches": [
        {
            "position": 1,
            "title": "Flood photo - News",
            "source": "News Example",
            "link": "https://news.example/story",
            "thumbnail": "https://serpapi.example/thumb1.jpg",
            "date": "Mar 5, 2024",
            "actual_image_width": 1200,
            "actual_image_height": 800,
        },
        {
            "position": 2,
            "title": "Shop",
            "source": "Shop",
            "link": "https://shop.example/p",
            "price": "$5",
        },
        {"position": 3, "title": "no link"},
    ],
}


def test_lens_parses_exact_matches_as_pages() -> None:
    hits = LensExactMatches("k").parse(json.dumps(LENS_BODY).encode())
    assert [h.page_url for h in hits] == ["https://news.example/story", "https://shop.example/p"]
    assert all(h.image_url is None for h in hits)
    assert hits[0].provider_date == datetime(2024, 3, 5, tzinfo=UTC)
    assert hits[0].raw["thumbnail"] == "https://serpapi.example/thumb1.jpg"
    assert hits[1].provider_date is None
    assert "price" not in hits[1].raw


def test_lens_dates() -> None:
    assert parse_lens_date("January 7, 2023") == datetime(2023, 1, 7, tzinfo=UTC)
    assert parse_lens_date("3 days ago") is None
    assert parse_lens_date(None) is None


async def test_lens_uploads_then_searches_by_image_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/image":
            return httpx.Response(
                200, json={"message": "Image uploaded successfully.", "image_id": "IMG123"}
            )
        return httpx.Response(200, json=LENS_BODY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        raw = await LensExactMatches("serp-key").fetch(_asset(), client)
    upload, search = seen
    assert (
        upload.method == "POST"
        and b"serp-key" in upload.content
        and b"\xff\xd8\xffjpeg" in upload.content
    )
    assert search.url.params["image_id"] == "IMG123"
    assert search.url.params["engine"] == "google_lens"
    assert search.url.params["type"] == "exact_matches"
    assert raw.units == 2


@pytest.mark.parametrize(
    ("error", "retryable"),
    [("Your account has run out of searches.", False), ("Please try again later.", True)],
)
async def test_serpapi_errors(error: str, retryable: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": error})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as exc:
            await LensExactMatches("k").fetch(_asset(), client)
    assert exc.value.retryable is retryable


async def test_serpapi_no_results_is_an_empty_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/image":
            return httpx.Response(200, json={"image_id": "X"})
        return httpx.Response(
            200, json={"error": "Google Lens hasn't returned any results for this query."}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        raw = await LensExactMatches("k").fetch(_asset(), client)
    assert LensExactMatches("k").parse(raw.body) == []


def test_large_uploads_are_fitted_under_the_limit() -> None:
    noisy = Image.effect_noise((2400, 1800), 90).convert("RGB")
    out = io.BytesIO()
    noisy.save(out, format="PNG")
    assert out.tell() > UPLOAD_MAX_BYTES
    fitted = fit_upload(out.getvalue())
    assert len(fitted) <= UPLOAD_MAX_BYTES
    assert fitted[:3] == b"\xff\xd8\xff"
    small = b"\xff\xd8\xff" + b"x" * 100
    assert fit_upload(small) is small


async def test_yandex_needs_a_public_url_and_parses_results() -> None:
    adapter = YandexImages("k")
    assert adapter.requires_public_url
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as client:
        with pytest.raises(ProviderError, match="public image URL"):
            await adapter.fetch(_asset(), client)
    body = {
        "images_results": [
            {
                "position": 1,
                "link": "https://p.example",
                "original": "https://p.example/i.jpg",
                "title": "t",
            }
        ]
    }
    [hit] = adapter.parse(json.dumps(body).encode())
    assert (hit.page_url, hit.image_url) == ("https://p.example", "https://p.example/i.jpg")
