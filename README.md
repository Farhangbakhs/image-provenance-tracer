# ORIGIN

An image provenance tracer for open-source investigators: it takes one image and returns a dated, evidence-backed history of its copies and edits.

> Earliest found in indexed sources. Earlier copies may exist.

## What it does

An analyst uploads an image. ORIGIN searches Google Lens, fetches every hit and keeps only those that are the same picture or an edit of it. It dates each copy from the signals it can find, reads the claim each page makes about the image, and shows where those claims diverge. Every finding links to the stored source behind it (SHA-256 and fetch time). The result exports as a JSON evidence pack or a printable PDF brief.

ORIGIN never reports an "origin". Private, deleted and unindexed posts are invisible to it, so every result is a bound, not a fact.

![The investigation page for a live trace: the answer sentence, stories as rows on a time axis, and the evidence for the earliest copy](docs/investigation.png)

## My role

I built ORIGIN alone: the pipeline, the database schema, the API, the web console and the matching evaluation.

## Run it

Running ORIGIN needs your own API keys. Both have free tiers:

- **SerpApi** for Google Lens reverse search (free plan: 250 searches a month).
- **Gemini** for reading claims from page text (Google AI Studio free tier).

Without them the stack starts but cannot trace a new image. The tests do not need keys, because they replay real recorded responses (see Testing).

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22, GNU Make. exiftool is needed only if you run outside Docker.

```sh
cp .env.example .env     # then set SERPAPI_API_KEY and GEMINI_API_KEY
make dev                 # db, redis, s3, migrate, api, worker, web; returns when all are healthy
```

| Service | URL |
| --- | --- |
| Console | http://localhost:3000 |
| API (OpenAPI docs at `/docs`) | http://localhost:8000/docs |
| Readiness | http://localhost:8000/readyz |

Open the console, create a case, upload an image and start a trace. `make down` stops the stack and keeps its data volumes. The first build downloads CPU PyTorch and the SSCD model weights (about 2 GB).

Windows note: use a standard GNU Make. The `make` that ships with GAMS cannot run these recipes.

### Reading a result

Open a case, then an image, then **Open investigation**. It starts with the answer in one sentence: where the earliest copy was found, when, and which story the original tells. Below that the copies appear as a **Graph** or a **List**. In the graph, each row is a story that pages tell about the image, and each dot is a copy on a shared time axis. Click a dot for its evidence. Switch to **How it looks** to see the variants and which edit was made from which.

Keys: `+` and `-` zoom, arrows pan, `0` resets, `j` and `k` step through copies, `e` opens evidence, `g` switches view. A trace verifies at most 50 hits, best-ranked first (`ORIGIN_VERIFY_MAX_CANDIDATES`). The rest are listed as not checked. **Trace again** reuses the stored search and costs no quota.

## How it works

```
apps/web (Next.js)  --HTTP / SSE-->  apps/api (FastAPI)
                                          | enqueue (arq)     ^ progress (Redis Streams)
                                          v                   |
                                    apps/worker --------------+
                                          |
          Postgres 16 + pgvector     Redis (jobs, run events)     S3-compatible store (artefacts)
```

The pipeline runs six stages: ingest, discover, verify, date, branch and report. Each stage reads from the database and object store only, so any stage can be re-run alone. The full design is in [docs/DESIGN.md](docs/DESIGN.md). The decisions that matter most:

- **The schema enforces the evidence rules.** A claim needs a sighting, narratives need a claim, the audit log is append-only and quota cannot be overspent. Why: a rule in Postgres holds whichever code path wrote the row. Trade-off: rules in constraints and triggers need a migration to change.
- **A provider hit is a candidate until ORIGIN fetches and verifies it.** Matching uses hashes (pHash, PDQ), an SSCD embedding and an ORB + RANSAC geometric check. Why: a search engine's "visual match" is not evidence. Trade-off: each hit costs a fetch, so a trace verifies at most 50.
- **Dates are bounds, not points.** Each timestamp signal is stored with its kind and confidence, and a reduction rule turns them into an interval. Why: a page's own date can be wrong, and the product must not overstate. Trade-off: a result can be an interval, not a single date.
- **Every provider call goes through one runner.** It hashes the request, serves stored responses without spending quota, reserves free-tier quota under a row lock, retries with backoff, trips a circuit breaker and records every outcome. Why: free-tier limits are hard limits. Trade-off: quota periods follow UTC calendar boundaries, which may differ from a vendor's billing cycle.
- **Replay fails loudly.** In replay mode a missing recording raises an error instead of returning no results. Why: an empty result would read as "no matches found", which is a false finding. Trade-off: tests fail until a recording exists.
- **Fetched pages are untrusted data.** They reach the language model only inside delimited blocks, and any quote it returns must be an exact substring of the source text. Why: this contains prompt injection from page text. Trade-off: a model answer that paraphrases is rejected and retried.

The language model sits behind one interface with three backends: Gemini (default, free tier), Ollama (local) and Anthropic (optional, paid, used only when `ANTHROPIC_API_KEY` is set).

## Testing and evaluation

```sh
make install   # Python 3.12 venv and web dependencies
make lint      # ruff, strict pyright, fixture verification, eslint, tsc
make test      # pytest and Vitest
make e2e       # Playwright against the running stack (make dev first)
make eval      # the matching eval; writes evals/report.md
make ci        # the CI jobs in clean Linux containers, against committed HEAD
```

The tests replay real recorded responses from `fixtures/recordings/` (Google Lens and Wayback, for one public-domain query image). They need no network and no keys. Database, Redis and S3 tests run against the compose services and are skipped when those are unreachable; CI requires them. Eighteen tests also need the SSCD model weights and are skipped until you download them once with `uv run python -m origin_worker.embedding download`. With the stack up and the weights downloaded, all 268 Python tests run. See [fixtures/README.md](fixtures/README.md).

`make eval` checks matching against 18 sample photographs, each edited 14 ways a repost is edited (resizes, recompression, mirrors, crops, caption bars, watermarks, screenshots), and against every pair of different photographs. The report is [evals/report.md](evals/report.md). Recall on edited copies is 93.7% (236 of 252) with thresholds `v2`, up from 75.4% (190 of 252) with `v1`, and false positives are 0.7% (2 of 306 unrelated pairs). Both false positives are one stereo pair, the same scene photographed from two slightly different positions.

## Limitations

The full list is in [docs/LIMITATIONS.md](docs/LIMITATIONS.md). The main points:

- A result is the earliest copy found in indexed sources. It is not proof of origin.
- A stereo pair is classified as a near-duplicate. Two frames from one burst would look the same.
- Heavy crops with a caption are the weakest edit: 11 of 18 found.
- The Cloud Vision and Yandex adapters are written from documentation and have not run against the live services.
- The investigator agent is not built.
- The Telegram integration is off by default. Telegram's terms restrict collecting and indexing its data. Read [docs/DESIGN.md](docs/DESIGN.md#7-telegram-integration) before enabling it. ORIGIN refuses the flag in production. Its tests use generated data, not recorded Telegram traffic.

## Data sources and licences

- **SerpApi** (Google Lens) and **Google AI Studio** (Gemini) are used under their free tiers and their terms.
- **Internet Archive** Wayback CDX is used for earliest-capture dates.
- **SSCD** (Meta) provides the image embedding. The code is MIT, and the maintainers state the weights are MIT too. The weights are downloaded at runtime, not redistributed here.
- **C2PA trust list** from `c2pa-org/conformance-public` (CC-BY-4.0), vendored and hash-checked.
- Test images and the matching eval's sample photographs come from the c2pa-python test fixtures and scikit-image. `fixtures/c2pa/test-es256-private.key` is c2pa-python's published test signing key, not a secret.
- `fixtures/queries/earthrise.jpg` is the public-domain Apollo 8 "Earthrise" photograph.

## Running cost

Zero. Default providers stay inside free tiers with hard stops below each limit, and every response is cached by content hash, so re-runs cost nothing. See [docs/DESIGN.md](docs/DESIGN.md#8-running-cost).
