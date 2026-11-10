"""The ordered list of pipeline stages the worker executes.

Stages are added here as each phase implements them (ingest, discover, verify, date, branch,
report). Until then a run completes with no stages executed.
"""

from __future__ import annotations

from origin_core.pipeline.runner import Stage

STAGE_ORDER: tuple[str, ...] = ("ingest", "discover", "verify", "date", "branch", "report")


def default_stages() -> list[Stage]:
    return []
