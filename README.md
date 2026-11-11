# ORIGIN

An image provenance tracer for open-source intelligence work. Give it one image and it returns a dated, evidence-backed history: the earliest sighting found, every verified copy and edit, and the points where the story told about the image changes.

> Earliest found in indexed sources. Earlier copies may exist.

ORIGIN never reports an "origin". Private, deleted and unindexed posts are invisible to it, so every result is a bound, not a fact.

## Status

Built phase by phase; see [PLAN.md](PLAN.md) for the specification, the verification log for every external service, and the phase list.

Phases 0 to 5 are built: ingest (hashes, metadata, Content Credentials, SSCD embedding), discovery through free-tier providers, verification of every hit by fetching and matching it, evidence-based dating, variants, claims, narratives and grades, the console with its timeline, variant graph, evidence drawer and exports, and Telegram behind a feature flag (below). Phase 6 has its matching eval, rate limits and end-to-end tests; the agent is not built.

## Try the demo (no keys, about five minutes)

Requirements: Docker and GNU Make.

```sh
make demo
```

This builds and starts the stack in replay mode and seeds four investigations. Open http://localhost:3000, pick a case and open its run.

| Case | What to look for |
| --- | --- |
| Flood photo recaptioned as a hurricane | Two early Valencia pages and a later mirrored repost that calls it Hurricane Milton in Florida. The timeline shows the root narrative and the branch, with its divergence sighting. |
| Cropped and captioned repost | A CDN resize and a blog crop with a caption bar, linked as derivatives in the graph; one unrelated hit and one dead link are rejected and counted. |
| Signed photo, stripped copies | The query carries Content Credentials from a test signer that is not on the trust list; the reposts lost them. |
| Harbour smoke posted on Telegram before the web | The Telegram sweep finds a watchlist channel's post from 12 May, two days before the earliest news page, and follows its forward header to the post it came from, dated 11 May. Both are dated by the post time Telegram shows. The lineage view draws the forward as a dashed arrow. |

In the workspace, `j`/`k` move through sightings, `e` opens the evidence drawer and `g` switches between the timeline, lineage and evidence views. Dotted-underlined terms explain themselves on hover, and **How to read this investigation** sums up the rest. **Brief (PDF)** opens a printable report; **Evidence pack (JSON)** downloads every finding with the SHA-256, fetch time and storage key of each artefact behind it.

What is synthetic in the demo, and labelled so in `fixtures/demo/cases.json`: the web pages, their `.example` domains, the archive dates, the reverse-image index, and the Telegram channels, posts and post times (served from memory; the demo never contacts Telegram). Everything ORIGIN does with them is real: each image is fetched through the hardened fetcher, fingerprinted, embedded, matched, dated, clustered, read for claims and graded by the same pipeline as a live trace. Claims and narratives were extracted once by a real model (Gemini, free tier) and are replayed from `fixtures/recordings/`.

## Share a read-only copy (free static hosting)

The four demo investigations can be published as a static site: about 2.6 MB of plain files, no server, no database, no running cost. Visitors can open every case, timeline, lineage view, evidence drawer and brief; uploads and new traces are switched off and explained.

```sh
make demo        # seed the demo cases (or make dev, if they are already seeded)
make snapshot    # writes apps/web/out
```

Only cases whose title starts with `DEMO:` are exported, so nothing you traced yourself leaves the machine. Publish `apps/web/out` on any static host:

* **Cloudflare Pages** (free, unlimited bandwidth): `npx wrangler login`, then `npx wrangler pages deploy apps/web/out --project-name origin-demo`.
* **Netlify** (free): drag the `apps/web/out` folder onto https://app.netlify.com/drop.
* **A sub-path host** such as GitHub Pages: build with `NEXT_PUBLIC_BASE_PATH=/<repo> make snapshot`.

To preview it locally: `uv run python -m http.server 4173 -d apps/web/out`, then open http://localhost:4173.

## Run it


For live traces with your own keys (see `.env.example`). Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node 22, GNU Make.

```sh
make dev       # db, redis, s3, migrate, api, worker, web; returns when all are healthy
```

| Service | URL |
| --- | --- |
| Console | http://localhost:3000 |
| API (OpenAPI docs at `/docs`) | http://localhost:8000 |
| Readiness | http://localhost:8000/readyz |

`make down` stops the stack and keeps its data volumes.

## Telegram (Phase 5, off by default)

Reverse-image engines do not index Telegram, so ORIGIN keeps its own index of photos from public channels that you list. **Read [PLAN.md 1.9](PLAN.md) first:** Telegram's API terms and its content-licensing terms restrict collecting and indexing its data, and ORIGIN refuses the flag in production.

```sh
export ORIGIN_ENABLE_TELEGRAM=true
uv run python -m origin_worker.telegram watch https://t.me/some_public_channel
uv run python -m origin_worker.telegram collect --pages 2    # public web preview, no account
```

With the flag on, every trace also asks the index, and a targeted sweep searches each watchlist channel around the earliest web date. A Telegram hit is verified like any web page and dated by its post time; forward headers are followed to public source posts and drawn as forward edges. Coverage is the watchlist: no Telegram hit means "not in the channels ORIGIN indexes". The optional Telethon collector (`uv sync --extra telegram`, then `login` and `collect --via api`) needs your own `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`; its session file is gitignored.

## Develop

```sh
make install   # Python 3.12 venv and web dependencies
make lint      # ruff, strict pyright, fixture verification, eslint, tsc
make test      # pytest and Vitest
make migrate   # apply migrations to DATABASE_URL
make client    # regenerate the typed web client after changing the API
make ci        # the CI jobs in clean Linux containers, against committed HEAD
make e2e       # Playwright against the running demo (make demo first)
make eval      # the matching eval; writes evals/report.md
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

## Evaluation

`make eval` checks matching against 18 sample photographs, each edited 14 ways a repost is edited (resizes, recompression, mirrors, crops, caption bars, watermarks, screenshots), and against every pair of different photographs. The current report is [evals/report.md](evals/report.md): thresholds `v2` find 93.7% of edited copies, against 75.4% for `v1`. The only false positives are a stereo pair, the same scene photographed from two slightly different positions, which perceptual hashes and SSCD both score as the same picture.

## Running cost

Zero. Default providers stay inside free tiers with hard stops below each limit, and every response is cached by content hash so re-runs spend nothing. See PLAN.md section 8.
