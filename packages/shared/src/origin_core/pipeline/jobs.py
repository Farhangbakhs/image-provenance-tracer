"""The job contract between the API (which enqueues) and the worker (which executes).

Kept in origin_core so the API can enqueue runs without importing the worker, and with it
PyTorch.
"""

from __future__ import annotations

import uuid

from arq.connections import ArqRedis

EXECUTE_RUN = "execute_run"


def run_job_id(run_id: uuid.UUID) -> str:
    """One job per run: enqueueing the same run twice is a no-op while the first is queued."""
    return f"run:{run_id}"


async def enqueue_run(pool: ArqRedis, run_id: uuid.UUID) -> bool:
    """Queue a run for the worker. False if a job for this run is already queued or running."""
    job = await pool.enqueue_job(EXECUTE_RUN, str(run_id), _job_id=run_job_id(run_id))
    return job is not None
