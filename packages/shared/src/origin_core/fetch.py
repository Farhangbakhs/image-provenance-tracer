"""The one hardened HTTP fetcher for everything ORIGIN downloads from the web.

Fetching URLs that strangers put on web pages is a server-side request forgery risk, so:

* only http and https on standard ports;
* every host is resolved first, and the request is refused if *any* resolved address is not a
  global unicast address (private, loopback, link-local, cloud metadata, multicast, reserved,
  IPv4-mapped forms of those);
* the connection goes to the vetted IP itself, with the Host header and TLS SNI set to the
  hostname, so DNS cannot be re-pointed between the check and the connection; TLS
  certificates are still verified against the hostname;
* redirects are followed manually, at most five, and every hop is checked again;
* bodies are streamed and cut off at a size cap, under an overall time limit;
* the fetcher identifies itself honestly.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

USER_AGENT = (
    "ORIGIN-provenance-tracer/0.1 (+https://github.com/Farhangbakhs/image-provenance-tracer)"
)
ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchBlocked(Exception):
    """The URL was refused before any request was made (scheme, port or address)."""


class FetchFailed(Exception):
    """The request was made but did not produce a usable response."""


@dataclass(frozen=True)
class FetchPolicy:
    max_bytes: int = 20_000_000
    timeout_s: float = 20.0
    max_redirects: int = 5


IMAGE_POLICY = FetchPolicy(max_bytes=20_000_000)
PAGE_POLICY = FetchPolicy(max_bytes=5_000_000)


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes = field(repr=False)
    fetched_at: datetime
    redirects: list[str]
    address: str

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _check_url(url: str) -> tuple[str, str, int]:
    """Return (scheme, host, port) or raise FetchBlocked."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchBlocked(f"scheme not allowed: {scheme or '(none)'}")
    if parts.username or parts.password:
        raise FetchBlocked("credentials in URLs are not allowed")
    host = parts.hostname
    if not host:
        raise FetchBlocked("URL has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise FetchBlocked(f"invalid port: {exc}") from exc
    if port not in ALLOWED_PORTS:
        raise FetchBlocked(f"port not allowed: {port}")
    return scheme, host, port


async def _vet_host(host: str, port: int, resolver: Resolver) -> str:
    """Resolve and vet a host; return one address to connect to."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    else:
        try:
            addresses = await resolver(host, port)
        except OSError as exc:
            raise FetchFailed(f"could not resolve {host}: {exc}") from exc
    if not addresses:
        raise FetchFailed(f"{host} resolved to no addresses")
    blocked = [a for a in addresses if not is_public_address(a)]
    if blocked:
        raise FetchBlocked(f"{host} resolves to a non-public address ({', '.join(blocked)})")
    return addresses[0]


def _pinned_url(url: str, address: str) -> str:
    parts = urlsplit(url)
    host = f"[{address}]" if ":" in address else address
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


class Fetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._resolver = resolver
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, policy: FetchPolicy = PAGE_POLICY) -> FetchResult:
        try:
            async with asyncio.timeout(policy.timeout_s):
                return await self._get(url, policy)
        except TimeoutError as exc:
            raise FetchFailed(f"timed out after {policy.timeout_s}s: {url}") from exc

    async def _get(self, url: str, policy: FetchPolicy) -> FetchResult:
        redirects: list[str] = []
        current = url
        while True:
            _, host, port = _check_url(current)
            address = await _vet_host(host, port, self._resolver)
            parts = urlsplit(current)
            host_header = parts.netloc.rsplit("@", 1)[-1]
            request = self._client.build_request(
                "GET",
                _pinned_url(current, address),
                headers={"Host": host_header},
                extensions={"sni_hostname": host},
            )
            try:
                response = await self._client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise FetchFailed(f"request failed: {exc!r}") from exc
            try:
                if response.status_code in REDIRECT_CODES and "location" in response.headers:
                    if len(redirects) >= policy.max_redirects:
                        raise FetchFailed(f"too many redirects (>{policy.max_redirects})")
                    redirects.append(current)
                    current = urljoin(current, response.headers["location"])
                    continue
                body = await self._read_capped(response, policy.max_bytes)
                return FetchResult(
                    requested_url=url,
                    final_url=current,
                    status=response.status_code,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=body,
                    fetched_at=datetime.now(UTC),
                    redirects=redirects,
                    address=address,
                )
            finally:
                await response.aclose()

    @staticmethod
    async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise FetchFailed(f"response is {declared} bytes; limit is {max_bytes}")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise FetchFailed(f"response exceeded {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
