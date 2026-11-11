"""Export the demo investigations as a static snapshot the console can serve with no server.

    uv run python scripts/snapshot.py [--api http://localhost:8000] [--out apps/web/public/snapshot]

Reads the running API (seed it first with `make demo`) and writes every response the console
needs for the cases whose title starts with "DEMO:": the case, asset and run documents as
`<path>.json`, and the query and sighting images at their API paths. Only demo cases are
exported, so no investigation of real images leaves the machine. For each asset, only its
newest succeeded run is kept.

The snapshot build of the console (`make snapshot`) reads these files instead of the API.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEMO_PREFIX = "DEMO:"


class Exporter:
    def __init__(self, api: str, out: Path) -> None:
        self.http = httpx.Client(base_url=api, timeout=60)
        self.out = out
        self.files = 0
        self.bytes = 0

    def get(self, path: str) -> Any:
        response = self.http.get(path)
        response.raise_for_status()
        return response.json()

    def write_json(self, path: str, payload: Any) -> None:
        target = self.out / f"{path.strip('/')}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        target.write_bytes(data)
        self.files += 1
        self.bytes += len(data)

    def copy_binary(self, path: str) -> None:
        response = self.http.get(path)
        response.raise_for_status()
        target = self.out / path.strip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        self.files += 1
        self.bytes += len(response.content)

    def run(self) -> dict[str, list[str]]:
        manifest: dict[str, list[str]] = {"cases": [], "assets": [], "runs": []}
        cases = [c for c in self.get("/cases") if str(c["title"]).startswith(DEMO_PREFIX)]
        if not cases:
            raise SystemExit("no DEMO: cases found; seed them first with `make demo`")
        self.write_json("/cases", cases)
        for case in cases:
            detail = self.get(f"/cases/{case['id']}")
            self.write_json(f"/cases/{case['id']}", detail)
            manifest["cases"].append(case["id"])
            for brief in detail["assets"]:
                asset = self.get(f"/assets/{brief['id']}")
                done = [r for r in asset["runs"] if r["status"] == "succeeded"][:1]
                asset["runs"] = done
                self.write_json(f"/assets/{asset['id']}", asset)
                self.copy_binary(asset["display_url"])
                manifest["assets"].append(asset["id"])
                for run in done:
                    self.export_run(run["id"])
                    manifest["runs"].append(run["id"])
        self.write_json("/manifest", manifest)
        return manifest

    def export_run(self, run_id: str) -> None:
        self.write_json(f"/runs/{run_id}", self.get(f"/runs/{run_id}"))
        sightings = self.get(f"/runs/{run_id}/sightings")
        self.write_json(f"/runs/{run_id}/sightings", sightings)
        self.write_json(f"/runs/{run_id}/analysis", self.get(f"/runs/{run_id}/analysis"))
        self.write_json(f"/runs/{run_id}/evidence-pack", self.get(f"/runs/{run_id}/evidence-pack"))
        for sighting in sightings["sightings"]:
            self.copy_binary(sighting["image_url_local"])


def main() -> None:
    parser = argparse.ArgumentParser(prog="snapshot")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--out", type=Path, default=ROOT / "apps" / "web" / "public" / "snapshot")
    args = parser.parse_args()
    if args.out.exists():
        shutil.rmtree(args.out)
    exporter = Exporter(args.api, args.out)
    manifest = exporter.run()
    print(
        f"exported {len(manifest['cases'])} cases, {len(manifest['runs'])} runs: "
        f"{exporter.files} files, {exporter.bytes / 1e6:.1f} MB -> {args.out}"
    )


if __name__ == "__main__":
    main()
