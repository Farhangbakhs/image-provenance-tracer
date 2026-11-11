"""Manage the Telegram watchlist and collect it (needs ORIGIN_ENABLE_TELEGRAM=true).

    python -m origin_worker.telegram watch CHANNEL [--note TEXT]   # add a public channel
    python -m origin_worker.telegram list                          # show the watchlist
    python -m origin_worker.telegram collect [CHANNEL ...] [--pages N] [--via preview|api]
    python -m origin_worker.telegram login                         # Telethon only, interactive

`collect` reads the public preview by default and needs no account. `--via api` uses Telethon
with TELEGRAM_API_ID, TELEGRAM_API_HASH and the session from `login`.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from origin_core.db.session import make_engine, make_sessionmaker
from origin_core.fetch import Fetcher
from origin_core.logging import configure_logging
from origin_core.settings import Settings, get_settings
from origin_core.storage import make_blob_store
from origin_worker.embedding import SSCDEmbedder, ensure_weights
from origin_worker.telegram.collector import Collector, SSCDModel, add_channel, watchlist
from origin_worker.telegram.sources import Pacer, PhotoSource, PreviewSource, TelethonSource


def _telethon(settings: Settings) -> TelethonSource:
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        raise SystemExit("--via api needs TELEGRAM_API_ID and TELEGRAM_API_HASH")
    return TelethonSource.connect(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash.get_secret_value(),
        session=settings.telegram_session,
        interval_s=settings.telegram_interval_s,
    )


async def _login(settings: Settings) -> None:
    client: Any = _telethon(settings).client
    await client.start()  # prompts for phone, code and password in this terminal
    me = await client.get_me()
    print(f"logged in; session saved to {settings.telegram_session} (id {me.id})")
    await client.disconnect()


async def _collect(settings: Settings, channels: list[str], *, pages: int, via: str) -> None:
    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    blobs = make_blob_store(settings)
    await blobs.ensure_ready()
    embedder = SSCDEmbedder(await ensure_weights(settings.models_dir))
    collector = Collector(
        sessions=sessions,
        blobs=blobs,
        embedder=SSCDModel(embedder),
        max_pixels=settings.upload_max_pixels,
        max_bytes=settings.upload_max_bytes,
    )
    fetcher = Fetcher()
    telethon: TelethonSource | None = None
    try:
        source: PhotoSource
        if via == "api":
            telethon = _telethon(settings)
            await telethon.client.connect()
            if not await telethon.client.is_user_authorized():
                raise SystemExit("not logged in: run `python -m origin_worker.telegram login`")
            source = telethon
        else:
            source = PreviewSource(fetcher, Pacer(settings.telegram_interval_s))
        names = channels or [row.channel for row in await watchlist(sessions)]
        if not names:
            raise SystemExit("the watchlist is empty: add a channel with `watch`")
        for name in names:
            report = await collector.collect(source, name, max_pages=pages)
            print(
                f"{name}: {report.indexed} indexed, {report.skipped} already indexed, "
                f"{report.rejected} rejected"
                + (f"; stopped: {report.stopped}" if report.stopped else "")
            )
    finally:
        if telethon is not None:
            await telethon.client.disconnect()
        await fetcher.aclose()
        await engine.dispose()


async def _watch(settings: Settings, channel: str, note: str | None) -> None:
    engine = make_engine(settings.database_url)
    try:
        name = await add_channel(make_sessionmaker(engine), channel, added_by="cli", note=note)
        print(f"watching {name}")
    finally:
        await engine.dispose()


async def _list(settings: Settings) -> None:
    engine = make_engine(settings.database_url)
    try:
        for row in await watchlist(make_sessionmaker(engine)):
            when = row.last_collected_at.isoformat() if row.last_collected_at else "never"
            print(f"{row.channel:32} newest {row.newest_collected_id or '-':>8}  collected {when}")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="origin_worker.telegram")
    sub = parser.add_subparsers(dest="cmd", required=True)
    watch = sub.add_parser("watch", help="add a public channel to the watchlist")
    watch.add_argument("channel")
    watch.add_argument("--note")
    sub.add_parser("list", help="show the watchlist")
    collect = sub.add_parser("collect", help="index photos from watchlist channels")
    collect.add_argument("channels", nargs="*")
    collect.add_argument("--pages", type=int, default=5, help="preview pages (20 posts each)")
    collect.add_argument("--via", choices=("preview", "api"), default="preview")
    sub.add_parser("login", help="log the Telethon session in (interactive)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    if not settings.enable_telegram:
        raise SystemExit("Telegram is off: set ORIGIN_ENABLE_TELEGRAM=true (read PLAN.md 1.9)")
    if args.cmd == "watch":
        asyncio.run(_watch(settings, args.channel, args.note))
    elif args.cmd == "list":
        asyncio.run(_list(settings))
    elif args.cmd == "collect":
        asyncio.run(_collect(settings, args.channels, pages=args.pages, via=args.via))
    else:
        asyncio.run(_login(settings))


if __name__ == "__main__":
    main()
