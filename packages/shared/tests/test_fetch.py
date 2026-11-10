"""The hardened fetcher: SSRF defences, redirect re-checks, IP pinning, size and time caps."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from origin_core.fetch import (
    USER_AGENT,
    FetchBlocked,
    Fetcher,
    FetchFailed,
    FetchPolicy,
    is_public_address,
)

PUBLIC = "93.184.216.34"
DNS = {
    "example.org": [PUBLIC],
    "cdn.example.org": ["151.101.1.1"],
    "rebind.example": ["127.0.0.1"],
    "mixed.example": [PUBLIC, "10.0.0.5"],
    "metadata.example": ["169.254.169.254"],
    "v6local.example": ["::1"],
    "mapped.example": ["::ffff:127.0.0.1"],
}


async def fake_resolver(host: str, port: int) -> list[str]:
    if host not in DNS:
        raise OSError(f"NXDOMAIN {host}")
    return DNS[host]


def _fetcher(handler: object) -> Fetcher:
    return Fetcher(resolver=fake_resolver, transport=httpx.MockTransport(handler))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
        "100.64.0.1",
    ],
)
def test_non_public_addresses_are_not_public(address: str) -> None:
    assert not is_public_address(address)


def test_public_addresses_are_public() -> None:
    assert is_public_address(PUBLIC)
    assert is_public_address("2606:4700:4700::1111")


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("file:///etc/passwd", "scheme"),
        ("ftp://example.org/a.jpg", "scheme"),
        ("http://127.0.0.1/", "non-public"),
        ("http://[::1]/", "non-public"),
        ("http://169.254.169.254/latest/meta-data/", "non-public"),
        ("http://rebind.example/", "non-public"),
        ("http://mixed.example/", "non-public"),
        ("http://metadata.example/", "non-public"),
        ("http://v6local.example/", "non-public"),
        ("http://mapped.example/", "non-public"),
        ("http://example.org:22/", "port"),
        ("http://user:pass@example.org/", "credentials"),
    ],
)
async def test_unsafe_urls_are_blocked_before_any_request(url: str, message: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    fetcher = _fetcher(handler)
    with pytest.raises(FetchBlocked, match=message):
        await fetcher.get(url)
    assert calls == []


async def test_connects_to_the_vetted_ip_with_host_and_sni() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "image/jpeg; q=1"}, content=b"jpeg")

    result = await _fetcher(handler).get("https://example.org/photo.jpg?x=1")
    [request] = seen
    assert request.url.host == PUBLIC
    assert request.url.path == "/photo.jpg" and request.url.query == b"x=1"
    assert request.headers["host"] == "example.org"
    assert request.extensions["sni_hostname"] == "example.org"
    assert request.headers["user-agent"] == USER_AGENT
    assert (result.status, result.body, result.content_type) == (200, b"jpeg", "image/jpeg")
    assert result.address == PUBLIC and result.final_url == "https://example.org/photo.jpg?x=1"


async def test_redirects_are_followed_and_rechecked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["host"] == "example.org":
            return httpx.Response(302, headers={"location": "https://cdn.example.org/i.jpg"})
        return httpx.Response(200, content=b"ok")

    result = await _fetcher(handler).get("https://example.org/start")
    assert result.final_url == "https://cdn.example.org/i.jpg"
    assert result.redirects == ["https://example.org/start"]


async def test_redirect_to_a_private_address_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(FetchBlocked, match="non-public"):
        await _fetcher(handler).get("https://example.org/")


async def test_redirect_loops_are_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(FetchFailed, match="too many redirects"):
        await _fetcher(handler).get("https://example.org/", FetchPolicy(max_redirects=3))


async def test_oversized_bodies_are_cut_off() -> None:
    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"x" * 999_999)

    with pytest.raises(FetchFailed, match="limit"):
        await _fetcher(declared).get("https://example.org/", FetchPolicy(max_bytes=1000))

    def undeclared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"x" * 5000))

    with pytest.raises(FetchFailed, match="exceeded"):
        await _fetcher(undeclared).get("https://example.org/", FetchPolicy(max_bytes=1000))


async def test_slow_responses_time_out() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    with pytest.raises(FetchFailed, match="timed out"):
        await _fetcher(handler).get("https://example.org/", FetchPolicy(timeout_s=0.2))


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200)


async def test_unresolvable_host_fails_cleanly() -> None:
    with pytest.raises(FetchFailed, match="could not resolve"):
        await _fetcher(_ok).get("https://nowhere.invalid/")
