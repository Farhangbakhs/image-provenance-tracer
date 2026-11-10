"""Run Alembic without an alembic.ini, so migrations ship inside the package.

Usage:
    python -m origin_core.db.migrate upgrade [revision]      (default: head)
    python -m origin_core.db.migrate downgrade <revision>
    python -m origin_core.db.migrate revision -m "message"  (autogenerates against DATABASE_URL)
    python -m origin_core.db.migrate check                   (fails if models and schema differ)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from origin_core.settings import get_settings

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    config.set_main_option("file_template", "%%(year)d%%(month).2d%%(day).2d_%%(rev)s_%%(slug)s")
    return config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="origin_core.db.migrate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("upgrade")
    up.add_argument("revision", nargs="?", default="head")
    down = sub.add_parser("downgrade")
    down.add_argument("revision")
    rev = sub.add_parser("revision")
    rev.add_argument("-m", "--message", required=True)
    sub.add_parser("check")
    args = parser.parse_args(argv)

    config = alembic_config()
    if args.cmd == "upgrade":
        command.upgrade(config, args.revision)
    elif args.cmd == "downgrade":
        command.downgrade(config, args.revision)
    elif args.cmd == "revision":
        command.revision(config, message=args.message, autogenerate=True)
    else:
        command.check(config)


if __name__ == "__main__":
    main()
