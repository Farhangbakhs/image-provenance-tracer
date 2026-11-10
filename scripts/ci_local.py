"""Run the CI workflow's checks locally, in clean Linux containers, against committed HEAD.

This mirrors .github/workflows/ci.yml for when GitHub Actions is unavailable. It tests
exactly what a push would publish: `git archive HEAD`, not the working tree, so uncommitted
or ignored files cannot make it pass.

Jobs run one at a time to keep memory low. While it runs, only the data services the tests
need (db, redis, s3) are up; the api, worker and web containers are stopped and restarted
afterwards if they were running.

Usage: python scripts/ci_local.py [python|web|images ...]   (default: python web)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra" / "compose.yaml")]
NETWORK = "origin_default"
APP_SERVICES = ["api", "worker", "web"]
DATA_SERVICES = ["db", "redis", "s3"]

PYTHON_JOB = """
set -e
mkdir /work && cd /work && tar xf /head.tar
# pyright's bundled Node needs libatomic, present on GitHub's runners but not slim Debian.
# exiftool is needed by the metadata tests.
apt-get update -qq
apt-get install -y -qq --no-install-recommends libatomic1 libimage-exiftool-perl >/dev/null
uv sync --frozen -q
echo '--- ruff';     uv run ruff check . && uv run ruff format --check .
echo '--- pyright';  uv run pyright
echo '--- fixtures'; uv run python -m origin_core.providers.fixtures verify
echo '--- pytest';   uv run pytest -q
"""

WEB_JOB = """
set -e
mkdir /work && cd /work && tar xf /head.tar && cd apps/web
npm ci --no-audit --no-fund --loglevel=error
echo '--- eslint'; npm run lint
echo '--- tsc';    npm run typecheck
echo '--- vitest'; npm test
echo '--- build';  npm run build
"""


def run(
    cmd: list[str], *, cwd: Path | None = None, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (fixed argv, no shell)
        cmd, cwd=cwd, check=False, text=True, capture_output=capture
    )


def running_services() -> set[str]:
    out = run([*COMPOSE, "ps", "--services", "--status", "running"], capture=True)
    return set(out.stdout.split())


def container(
    image: str, script: str, tar: Path, *, env: dict[str, str], volumes: list[str]
) -> int:
    cmd = ["docker", "run", "--rm", "--network", NETWORK, "-v", f"{tar}:/head.tar:ro"]
    for volume in volumes:
        cmd += ["-v", volume]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [image, "sh", "-c", script]
    return run(cmd).returncode


def job_python(tar: Path) -> int:
    return container(
        "ghcr.io/astral-sh/uv:python3.12-bookworm",  # full image: C++ toolchain for pdqhash
        PYTHON_JOB,
        tar,
        env={
            "ORIGIN_REQUIRE_SERVICES": "1",
            "TEST_DATABASE_URL": "postgresql+asyncpg://origin:origin@db:5432/origin_test",
            "TEST_REDIS_URL": "redis://redis:6379/15",
            "TEST_S3_ENDPOINT": "http://s3:8333",
            "UV_CACHE_DIR": "/cache/uv",
            "UV_LINK_MODE": "copy",
        },
        volumes=["origin-ci-cache:/cache"],
    )


def job_web(tar: Path) -> int:
    return container(
        "node:22.21-alpine",
        WEB_JOB,
        tar,
        env={"npm_config_cache": "/cache/npm", "NEXT_TELEMETRY_DISABLED": "1"},
        volumes=["origin-ci-cache:/cache"],
    )


def job_images(_: Path) -> int:
    steps = [
        [*COMPOSE, "config", "--quiet"],
        [
            "docker",
            "build",
            "-q",
            "-f",
            "infra/docker/python.Dockerfile",
            "-t",
            "origin-python:ci",
            ".",
        ],
        [
            "docker",
            "build",
            "-q",
            "-f",
            "infra/docker/web.Dockerfile",
            "-t",
            "origin-web:ci",
            "apps/web",
        ],
    ]
    for step in steps:
        if run(step, cwd=ROOT).returncode != 0:
            return 1
    return 0


JOBS = {"python": job_python, "web": job_web, "images": job_images}


def main(argv: list[str]) -> int:
    names = argv or ["python", "web"]
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        print(f"unknown job(s): {unknown}; choose from {sorted(JOBS)}", file=sys.stderr)
        return 2

    dirty = run(["git", "status", "--porcelain"], cwd=ROOT, capture=True).stdout.strip()
    head = run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture=True).stdout.strip()
    print(
        f"Checking committed HEAD {head}"
        + (" (uncommitted changes are NOT tested)" if dirty else "")
    )

    was_running = running_services() & set(APP_SERVICES)
    if was_running:
        run([*COMPOSE, "stop", *sorted(was_running)], capture=True)
    run([*COMPOSE, "up", "-d", "--wait", *DATA_SERVICES], cwd=ROOT)

    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "head.tar"
        run(["git", "archive", "--format=tar", "-o", str(tar), "HEAD"], cwd=ROOT)
        try:
            for name in names:
                print(f"\n=== {name} ===", flush=True)
                started = time.monotonic()
                results[name] = JOBS[name](tar) == 0
                verdict = "passed" if results[name] else "FAILED"
                print(f"=== {name} {verdict} in {time.monotonic() - started:.0f}s ===", flush=True)
        finally:
            if was_running:
                run([*COMPOSE, "start", *sorted(was_running)], capture=True)

    print("\n" + "  ".join(f"{n}: {'ok' if ok else 'FAILED'}" for n, ok in results.items()))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
