"""The order of the pipeline's stages.

The worker builds the stage objects (origin_worker.stages); the API uses this order to show
progress for stages that have not started yet. Stages are added as each phase implements them.
"""

from __future__ import annotations

from collections.abc import Iterable

STAGE_ORDER: tuple[str, ...] = ("ingest", "discover", "verify", "date", "branch", "report")
#: Stages that run only when a feature is on, and the stage each one follows.
OPTIONAL_STAGES: dict[str, str] = {"telegram_sweep": "date"}


def stage_order(present: Iterable[str] = ()) -> list[str]:
    """The stage order for a run: the fixed stages plus any optional stage the run recorded."""
    order = list(STAGE_ORDER)
    seen = set(present)
    for stage, after in OPTIONAL_STAGES.items():
        if stage in seen:
            order.insert(order.index(after) + 1, stage)
    return order
