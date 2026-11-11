"""Per-client rate limits on the endpoints that cost something: uploads (storage, decoding) and
trace runs (provider quota). A fixed window in Redis, shared by every API process."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from origin_api.state import get_state


def client_key(request: Request) -> str:
    """The socket peer. Behind a proxy, configure the proxy to set the peer (uvicorn
    `--proxy-headers` with `--forwarded-allow-ips`); a raw X-Forwarded-For is never trusted."""
    return request.client.host if request.client else "unknown"


def limit(
    action: str, per_minute: Callable[[Request], int]
) -> Callable[[Request], Awaitable[None]]:
    """A dependency that allows `per_minute(request)` calls per client per minute; 0 disables."""

    async def check(request: Request) -> None:
        allowed = per_minute(request)
        if allowed <= 0:
            return
        state = get_state(request)
        now = time.time()
        window = int(now // 60)
        key = f"ratelimit:{action}:{client_key(request)}:{window}"
        async with state.redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, 120)
            count, _ = await pipe.execute()
        if int(count) > allowed:
            retry = max(1, int(60 - now % 60))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"too many {action} requests: {allowed} per minute; retry in {retry} s",
                headers={"Retry-After": str(retry)},
            )

    return check


uploads = limit("upload", lambda r: get_state(r).settings.rate_limit_uploads)
runs = limit("run", lambda r: get_state(r).settings.rate_limit_runs)
