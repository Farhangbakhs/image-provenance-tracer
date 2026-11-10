"""The order of the pipeline's stages.

The worker builds the stage objects (origin_worker.stages); the API uses this order to show
progress for stages that have not started yet. Stages are added as each phase implements them.
"""

from __future__ import annotations

STAGE_ORDER: tuple[str, ...] = ("ingest", "discover", "verify", "date", "branch", "report")
