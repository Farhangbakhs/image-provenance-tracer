# ORIGIN

An image provenance tracer for open-source intelligence work. Give it one image and it returns a dated, evidence-backed history: the earliest sighting found, every verified copy and edit, and the points where the story told about the image changes.

> Earliest found in indexed sources. Earlier copies may exist.

ORIGIN never reports an "origin". Private, deleted and unindexed posts are invisible to it, so every result is a bound, not a fact.

## Status

Built phase by phase; see [PLAN.md](PLAN.md) for the specification, the verification log for every external service, and the phase list.

**Phase 0 (foundations) is complete.** The stack runs, and the evidence schema, provider runner (cache, quota, retries, circuit breaker, record and replay) and resumable pipeline with live progress are in place and tested. No pipeline stages exist yet; Phase 1 adds ingest. Demo mode, evaluation results and the ethics section arrive with later phases.

## Run it

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node 22, GNU Make.

```sh
make dev       # db, redis, s3, migrate, api, worker, web; returns when all are healthy
```

| Service | URL |
| --- | --- |
| Console | http://localhost:3000 |
| API (OpenAPI docs at `/docs`) | http://localhost:8000 |
| Readiness | http://localhost:8000/readyz |

`make down` stops the stack and keeps its data volumes.

## Develop

```sh
make install   # Python 3.12 venv and web dependencies
make lint      # ruff, strict pyright, fixture verification, eslint, tsc
make test      # pytest and Vitest
make migrate   # apply migrations to DATABASE_URL
make client    # regenerate the typed web client after changing the API
make ci        # the CI jobs in clean Linux containers, against committed HEAD
```

Database, Redis and S3 tests run against the compose services (`make dev` first) and are skipped when those are unreachable; CI requires them. Copy `.env.example` to `.env` to override any setting; every variable is documented there.

## Architecture

```
apps/web (Next.js)  ──HTTP / SSE──▶  apps/api (FastAPI)
                                          │ enqueue (arq)     ▲ progress (Redis Streams)
                                          ▼                   │
                                    apps/worker ──────────────┘
                                          │
          Postgres 16 + pgvector     Redis (jobs, run events)     S3-compatible store (artefacts)
```

* **Every provider call goes through one runner.** It hashes the request, serves stored responses without spending quota, reserves free-tier quota under a row lock, retries with backoff, trips a circuit breaker on repeated failure, and records a `provider_calls` row for every outcome.
* **Everything is replayable.** Raw responses and fetched artefacts are stored content-addressed by SHA-256. In replay mode providers are served only from `fixtures/`, with no network and no keys; see [fixtures/README.md](fixtures/README.md).
* **The schema enforces the evidence rules.** Claims need a sighting, narratives need a claim, the audit log is append-only, quota cannot be overspent.

## Running cost

Zero. Default providers stay inside free tiers with hard stops below each limit, and every response is cached by content hash so re-runs spend nothing. See PLAN.md section 8.
