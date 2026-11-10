"""Write the OpenAPI schema without starting the server: `python -m origin_api.openapi <path>`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from origin_api.app import create_app
from origin_core.settings import Settings


def main(argv: list[str]) -> None:
    target = Path(argv[1]) if len(argv) > 1 else Path("apps/web/openapi.json")
    schema = create_app(Settings()).openapi()
    target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main(sys.argv)
