# ORIGIN: design record

ORIGIN is an image provenance tracer for open-source investigation. An analyst uploads one image. ORIGIN finds where it has appeared online, checks that each appearance is the same picture or a derivative, dates each appearance with explicit uncertainty, and shows where the stories told about the image diverge. Every statement in the output cites a stored piece of evidence.

This document records the design decisions and the trade-offs accepted. Open items and known failure cases are in [LIMITATIONS.md](LIMITATIONS.md).

## 1. Principles

1. A provider hit is a **candidate**. It becomes a **sighting** only after ORIGIN fetches the image and verifies it.
2. Dates are **bounds**. Each timestamp signal is stored separately with its kind, bound type (`exact`, `no_later_than`, `claimed`) and confidence. The product says "earliest found", never "origin" or "first posted".
3. **No uncited claims.** Claims, narratives and edges reference existing sighting and evidence IDs. The schema enforces this, and model output that cites unknown IDs is rejected and retried.
4. Fetched web content is **untrusted data**. It reaches models only inside delimited blocks, under a system prompt that forbids following instructions inside them.
5. **No face recognition and no identification of people.**
6. **Everything is replayable.** Raw provider responses and fetched artefacts are stored with SHA-256 and fetch time.
7. **Adapters are written from current vendor documentation and recorded responses**, not from memory.

Every screen and export that shows an earliest date also shows: "Earliest found in indexed sources. Earlier copies may exist."

## 2. Architecture

```
apps/web (Next.js 16, App Router)  --HTTP/SSE-->  apps/api (FastAPI)
                                                       | enqueue (arq)    ^ progress (Redis Streams)
                                                       v                  |
                                                 apps/worker (arq) -------+
                                                       |
              Postgres 16 + pgvector   Redis (jobs, run events)      SeaweedFS / R2 (artefacts)
```

The repository is a monorepo:

```
apps/api        FastAPI app, routes, SSE relay, OpenAPI schema
apps/worker     arq worker, pipeline stages
apps/web        Next.js console
packages/shared Python package `origin_core`: models, db and migrations, providers, pipeline, storage
infra           docker compose, Dockerfiles, SeaweedFS identities
evals           labelled eval set manifest, harness, report
fixtures        recorded real provider responses and the public-domain query image
```

One uv workspace holds `origin_core`, `api` and `worker`. The API and the worker share models and the database layer through `origin_core`.

## 3. Pipeline

Each stage is idempotent and resumable. It records start, end, counts, quota used and errors on `runs.stages` (JSON per stage). Each stage reads only from the database and object store, so any stage can be re-run alone.

1. **Ingest.** Check magic bytes (JPEG, PNG, WebP, GIF first frame, HEIC if libheif is present). Caps: 20 MB and 50 MP. Store the original untouched and a re-encoded display copy. Compute SHA-256, pHash and dHash (imagehash), PDQ with quality and its dihedral variants, and the SSCD embedding. Extract EXIF, XMP and IPTC with `exiftool -j -G1`. Read C2PA and record `none`, `present_untrusted` or `valid_trusted` plus the raw report.
2. **Discover.** Fan out through `ProviderAdapter`:
   ```python
   class ProviderAdapter(Protocol):
       name: str; unit_cost: int; requires_public_url: bool; sends_bytes_to: str
       async def search(self, asset: AssetRef, ctx: ProviderContext) -> ProviderResult  # candidates + raw + units
   ```
   Defaults are `vision` (bytes) and `lens` (bytes via `image_id`). Optional adapters are `yandex` (public URL), `tineye` (paid key), `unofficial` (PicImageSearch; local only, gated), `fixture` (replay) and `telegram` (section 7). Each call goes through one wrapper that handles timeout, retry with jittered backoff, a circuit breaker, the quota check-and-debit, and a response cache keyed by `(provider, sha256, params_hash)`.
3. **Verify.** One hardened fetcher retrieves each candidate image and page. Classification uses thresholds in `matching/thresholds.v*.toml`:
   - `exact`: equal SHA-256.
   - `near_duplicate`: pHash Hamming distance <= 8 or PDQ <= 31 (or any PDQ dihedral <= 31, which also sets a mirror/rotation flag).
   - `derivative`: SSCD cosine >= 0.75 **and** an ORB + RANSAC homography with >= 15 inliers. It records crop box, mirror flag, scale and overlay likelihood (from the residual difference outside the matched regions). Thresholds v2 adds a second route, see section 5.
   - otherwise `unrelated`: dropped from sightings, kept in `candidates` with the reason.

   The threshold version is stored on every sighting.
4. **Date.** Signals are the platform timestamp, C2PA signed time, Wayback first capture (page URL and image URL), provider crawl date, page metadata (htmldate plus `article:published_time` and JSON-LD), HTTP `Last-Modified` and EXIF `DateTimeOriginal`. The reduction rule (`dating/rule.py`, unit-tested) is:
   - `exact` signals with high confidence define the point. With several, take the earliest and flag a conflict if they differ by more than 24 hours.
   - `no_later_than` signals set the interval's upper bound (the minimum of them).
   - `claimed` signals (page metadata, EXIF, `Last-Modified`) can narrow the interval only when they sit below the upper bound, and they cap confidence at medium.
   - The lower bound is the latest of: the earliest claimed date consistent with the upper bound, the C2PA time, or "unknown" (open interval).
   - Confidence is the highest confidence among the signals that actually set a bound. The deciding signal is stored.

   The vocabulary also includes `no_earlier_than` (a capture or signing time floors a sighting) and `observed` (ORIGIN's own fetch caps it).
5. **Branch.**
   - Variants: union-find over pairwise near-duplicate links. Derived-from edges come from containment (a crop is a child of the wider frame), resolution (lower from higher) and overlay (captioned from clean). Time only breaks ties. Each edge stores its reason code and evidence.
   - Claims: the model extracts `{event, place, date, actor_role, stance, quote_start, quote_end, language, translation}` per sighting. Output must validate against a JSON schema, the quote must be an exact substring of the delimited source text, and `sighting_id` must exist. On failure it retries up to twice, then records an extraction failure. `actor_role` describes roles ("protesters", "army"), never named private individuals.
   - Narratives: the earliest-dated claim seeds the root narrative. Each later claim is compared to every narrative on event, place and date (model judgement with cited IDs, plus deterministic checks on normalised place and date). A contradiction opens a new branch whose divergence sighting is the earliest claim in it.
   - Grading on the Admiralty scale. Reliability A to F comes from `sources` (a seeded list, default F, "cannot be judged"). Credibility 1 to 6 per sighting is computed from match class, the number of independent dating signals, archive presence and agreement with the earliest narrative. The rationale is stored as text.
6. **Report.** Timeline, graph and evidence-pack API; a JSON export and a printable PDF brief.

## 4. Data model

UUID primary keys and `timestamptz` (UTC) throughout. Tables: `cases`, `assets`, `runs`, `provider_calls`, `provider_quota`, `candidates`, `sightings`, `timestamp_evidence`, `variants`, `variant_edges`, `propagation_edges`, `claims`, `narratives`, `narrative_claims`, `sources`, `audit_events`, `artefacts` (content-addressed store index), plus the Telegram tables in section 7.

Rules the schema enforces:

- `claims.sighting_id` is `NOT NULL` with a foreign key. Narratives are inserted only together with at least one `narrative_claims` row (deferred constraint trigger).
- `audit_events` is append-only: a trigger rejects UPDATE, DELETE and TRUNCATE.
- `sightings.embedding vector(512)` has an HNSW index (`vector_cosine_ops`).
- Every `artefacts` row has `sha256`, `fetched_at`, `source_url`, `content_type` and `byte_size`.
- `provider_quota(provider, period_start, period_kind, limit, used)` is debited under a row lock, and a check constraint stops `used` exceeding `limit`.
- Date intervals are ordered.

## 5. Design decisions

| Decision | Why | Trade-off accepted |
| --- | --- | --- |
| **Integrity rules live in Postgres** | A claim without a sighting, an edited audit row or an overspent quota is rejected whatever code path produced it. | Rules are harder to change than application code, and each needs a migration. |
| **Provider response cache is durable** (`provider_calls` plus artefacts), not Redis | A cache hit survives restarts and is itself evidence. Redis keeps only jobs and run events. | Every provider call writes to Postgres and the object store. |
| **Run events use Redis Streams**, not pub/sub | A late or reconnecting browser resumes from `Last-Event-ID` without missing a stage. | More Redis state to keep than pub/sub, which keeps none. |
| **Replay mode fails loudly** on a missing recording | An empty result would read as "no matches found", which is a false finding. | Tests fail whenever a recording is absent, and recordings must be refreshed deliberately. |
| **Quota periods align to UTC calendar boundaries** | Simple and testable. | Vendors may reset on a billing anniversary. The Vision hard stop at 950 of 1,000 free units absorbs the mismatch. |
| **`propagation_edges` beside `variant_edges`** | Forwards and credits link *sightings*; derivations link *variants*. One table would leave half its columns empty. | Two edge tables to keep consistent. |
| **Migrations ship inside `origin_core`** (`python -m origin_core.db.migrate`) | The container image can migrate itself, and there is no `alembic.ini` to keep in sync. | Non-standard Alembic layout. |
| **Ingest is split between API and worker** | Validation, storage, hashes, exiftool and C2PA run at upload, so a bad file is refused at the door. The SSCD embedding runs in the worker, so only the worker loads PyTorch. | The embedding is not available at upload time, only once the worker's ingest stage has run. |
| **Metadata never invents certainty** | A capture time without a zone offset is shown as stated, never as UTC. GPS without a hemisphere is left unknown. exiftool failing is "unavailable", not "no metadata". | Some images show less information than a guess would give. |
| **Invalid C2PA manifests stay distinguishable** | The schema has three states, but the raw validation state and failure codes are stored and shown, so "invalid" never reads as merely "untrusted". | More states for the interface to explain. |
| **Official C2PA trust list vendored and hash-checked** | It comes from `c2pa-org/conformance-public` at commit `64b3f9c` (CC-BY-4.0). Every C2PA result records the list it was judged against. | The list goes stale until it is updated by hand. |
| **Thresholds v2 adds a geometric route to "derivative"** | A real crop-and-caption copy scored SSCD 0.69, below the v1 cut. v2 also accepts SSCD >= 0.5 when ORB + RANSAC finds >= 60 inliers. Every sighting stores the version it was judged by. | A lower embedding floor admits more candidates, so the route also requires 60 geometric inliers. Measured recall and false positives are in `evals/report.md`. |
| **The fetcher pins the vetted IP** | DNS is resolved once, every address must be global, and the connection goes to that address with SNI set, so a rebinding answer cannot redirect it. Redirects are re-vetted hop by hop. | Each hop is limited to the one address resolved for it. |
| **Only a contradiction opens a branch** | When the model groups claims apart without marking a contradiction, the groups join the root narrative. The model judges contradiction; the root is decided by evidence (the earliest-dated claim). | Divergences the model does not mark as contradictions stay on one branch. |
| **The brief is a print stylesheet**, not WeasyPrint | The brief page renders the evidence pack and prints to PDF from any browser. Playwright's `page.pdf()` checks it in the e2e suite. No extra Python dependency or system libraries. | PDF layout depends on the browser's print engine. |
| **Evidence pack format `origin.evidence-pack.v1`** | One JSON document holds findings, provider calls, the audit trail and every artefact with SHA-256, fetch time and storage key. | The format is versioned, so a later change needs a new version. |
| **CPU-only PyTorch from the PyTorch index** | The default Linux wheels bundle about 2.5 GB of CUDA. | The Python image is still about 2.1 GB. |
| **Model weights are downloaded, verified and never committed** | `python -m origin_worker.embedding download` fetches them. The SHA-256 is pinned, and tests never download. CI fetches in a setup step and requires the model. | First build needs network and about 2 GB. |
| **c2pa-python pinned to 0.38.0** | 0.38.1 and 0.38.2 were published with macOS wheels only. | Newer fixes are missed until wheels exist. |
| **Worker health check reads arq's heartbeat key** | `arq --check` imports PyTorch and outlasts the check timeout. The heartbeat refreshes every 30 seconds. | The check proves liveness, not that a job would succeed. |
| **Gemini model `gemini-3.5-flash-lite` as the default** | `gemini-2.5-flash` is closed to new free-tier keys, and `3.8-flash` answered too slowly on the free tier for claim extraction. | Lower extraction quality than a larger model. |
| **Local CI (`make ci`)** | It runs the same jobs as CI in Linux containers against committed HEAD, so the Linux-only build of pdqhash is exercised locally. | It is slow and stops the app containers while it runs. |

### Object storage

MinIO stopped publishing community Docker images (`minio/minio` returns 404 on Docker Hub, and the quay.io mirror is frozen at a 2025 release with an unpatched CVE). Development uses SeaweedFS 4.51 (Apache-2.0) with its S3 gateway on port 8333. The application speaks only the S3 API, so Cloudflare R2 is unchanged for deployment.

### LLM providers

All backends sit behind one `LLMProvider` interface. Tests use recorded outputs and need none of them.

| Option | Cost | Trade-off |
| --- | --- | --- |
| Gemini 2.5 Flash class, free tier (default) | Free | Strong structured JSON output and multilingual, which translation needs. Free-tier prompts and outputs are used by Google to improve its products, and rate limits are modest. |
| Ollama with a local model (for example Qwen 3 8B or Llama 3.x 8B) | Free | Private and offline. Slower on CPU and weaker at extraction, and it needs about 8 GB of free RAM. |
| Anthropic Claude (`origin_core/llm/claude.py`) | Paid key | Best quality. Used only when `ANTHROPIC_API_KEY` is set and `ORIGIN_LLM_PROVIDER=anthropic`. |

Fetched page text sent to a free tier is public web content, but the vendor keeps it.

### Interface

A dark console with one accent, `#22BED2`, which marks the earliest found, the selection, focus and the primary action. Everything else is greyscale, from Blueprint-style greys (`#111418` to `#383E47`). Base type is 14 px, labels are small uppercase, and data is monospaced. Confidence is a step of grey and is always written out. All times are UTC with a trailing `Z`.

- **The answer comes first.** A first walkthrough as a new user found the answer four clicks deep behind a page that repeated it, timeline bands that all spanned 2013 to today, two competing time charts, wheel zoom that hijacked page scrolling, five colours and three copies of the disclaimer. The image page now shows the answer and one primary action, the investigation opens with the answer and has two views (Graph, List), and the disclaimer lives in one global strip.
- **Explain in place.** Every technical term (sighting, variant, near-duplicate, interval, Admiralty grades) is a `<Term>` with a plain definition on hover or focus. Each copy carries one-sentence readings of its match, its dating and its grade.
- **One graph, two groupings.** The narrative timeline and the lineage both plotted copies over time and confused new users, so they are one force graph (d3-force through `react-force-graph-2d`, both MIT) with a switch: group by how a copy looks (variant) or by what its page claims (story). Each node is the copy's image, held at the earliest date its evidence allows. Edits and Telegram forwards are the only links. Zoom is Ctrl/Cmd + scroll, pinch, buttons or date chips, so the page keeps scrolling. A list of the graph in words serves screen readers.
- **Keyboard.** Ctrl/Cmd+K palette, `j`/`k` through sightings, `e` opens evidence, `g` cycles views.

## 6. Vendor documentation check (2026-11-10)

What was confirmed or corrected against live documentation before the adapters were written.

| Item | Assumed | Found | Source | Effect |
| --- | --- | --- | --- | --- |
| SerpApi free plan | 250 searches/month, 50/hour | **Confirmed.** Only successful searches count. | [serpapi.com/pricing](https://serpapi.com/pricing) | Quota meter defaults: `serpapi` 250/month, 50/hour. |
| SerpApi Google Lens input | Needs a public URL, so a presigned link | **Corrected.** Lens takes `url` **or** `image_id`. The Image API (`POST https://serpapi.com/image`, multipart field `image`) returns an `image_id` that expires after 10 minutes. Limits: JPG, PNG or WebP, at most 500 KB. | [Image API](https://serpapi.com/image-api), [Lens upload guide](https://serpapi.com/google-lens-upload-an-image), [Lens API](https://serpapi.com/google-lens-api) | The Lens adapter uploads bytes and needs no public URL. Images over 500 KB get a re-encoded copy (max 1600 px long edge, JPEG quality stepped down until it fits). The copy is stored, hashed and logged. |
| SerpApi Lens `type` | Exact and visual matches | **Confirmed.** `type` is `all`, `exact_matches` or `visual_matches`. The exact-match response shape is not fully documented. | [Lens API](https://serpapi.com/google-lens-api) | One `exact_matches` call per trace by default (one search). Adapter contract tests are written from the first real recorded response. |
| SerpApi Yandex | Same URL requirement | **URL only.** `engine=yandex_images&url=...`. `image_id` support is not documented for Yandex. | [Yandex Images API](https://serpapi.com/yandex-images-api) | Yandex needs a short-lived public URL. The local object store is not public, so Yandex is **off by default** until a public store (Cloudflare R2 free tier) or a confirmed `image_id` route exists. "Local providers only" mode excludes it. |
| Google Cloud Vision web detection | First 1,000 units/month free, billing account needed | **Confirmed from secondary sources.** Web Detection then costs $3.50 per 1,000. The official page did not render in the fetch tool. | [cloud.google.com/vision/pricing](https://cloud.google.com/vision/pricing) | Quota default: 1,000 units/month with a **hard stop at 950**, so a miscount cannot bill. |
| Vision request shape | Accepts bytes | **Confirmed.** `POST https://vision.googleapis.com/v1/images:annotate` with base64 `image.content` and `features[{type: WEB_DETECTION}]`. Docs show OAuth or ADC; an API key restricted to the Vision API also works on `?key=`. | [detecting-web](https://docs.cloud.google.com/vision/docs/detecting-web) | Adapter auth: API key first, service account JSON as fallback. |
| SSCD | Confirm the weight licence | Code is MIT, and the README stated no licence for the weights. The maintainers later confirmed the whole project, weights included, is MIT ([issue #12](https://github.com/facebookresearch/sscd-copy-detection/issues/12)). Preprocessing: RGB, `Resize(288)`, ImageNet mean/std. Output is a 512-d L2-normalised vector. | [facebookresearch/sscd-copy-detection](https://github.com/facebookresearch/sscd-copy-detection) | Weights are downloaded at runtime and never committed or redistributed. |
| pdqhash | Not checked | v0.2.8, MIT bindings; the PDQ source carries its own licence. Wheels exist for CPython 3.10 to 3.13 on Windows and macOS only. **No Linux wheels.** | [pypi.org/project/pdqhash](https://pypi.org/project/pdqhash/) | Docker images need a C++ toolchain to build pdqhash. The project stays on Python 3.12. `compute_dihedral` gives a cheap mirror and rotation check. |
| c2pa-python | Three trust states | v0.38.x, MIT/Apache-2.0, Python >= 3.10. Trust anchors are set through `Settings.from_dict`. | [c2pa-python](https://github.com/contentauth/c2pa-python) | ORIGIN maps the report to `none`, `present_untrusted` or `valid_trusted`. |
| Wayback CDX | Free, keyless, rate-limited | **Confirmed.** `GET http://web.archive.org/cdx/search/cdx?url=...&output=json&limit=1`. Results sort by URL, then time. | [wayback-cdx-server](https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server) | Earliest capture is `limit=1`. One request per second, exponential backoff, cached forever (a first capture never changes). |
| PicImageSearch | MIT, unofficial | **Confirmed.** v3.12.11, MIT. | [PyPI](https://pypi.org/pypi/PicImageSearch/json) | Opt-in, local only, behind `ORIGIN_ENABLE_UNOFFICIAL_PROVIDERS=true`, and refused at startup when `ORIGIN_ENV=production`. |
| Hosted free LLM tier | Pick one | The Gemini API free tier covers several Flash and Flash-Lite models. Free-tier prompts and outputs are used to improve Google's products. | [aistudio.google.com/docs/pricing](https://aistudio.google.com/docs/pricing) | See "LLM providers" above. |
| SerpApi Image API billing | Unknown whether an upload counts as a search | **Measured on 2026-11-11: it does not.** One upload plus one Lens search moved `this_month_usage` from 0 to 1 (`/account.json`). | `/account.json` | The meter charges one unit per Lens trace. |

Consequences:

1. Lens no longer needs a public URL, which removes its main privacy cost. Yandex still needs one.
2. Yandex cannot run in pure local development without a public object store. It is off by default, and enabling it requires `S3_PUBLIC_ENDPOINT` and is listed in the upload disclosure.
3. pdqhash has no Linux wheels, so the Docker images include a build stage.

## 7. Telegram integration

Reverse-image engines do not index Telegram. ORIGIN can keep its own index of photos from public channels that the user lists. It is off by default behind `ORIGIN_ENABLE_TELEGRAM`, and the settings refuse it in production.

### Terms analysis (2026-11-11)

The terms that apply conflict with a bulk-indexing design, so the integration is for local research use only.

- **API Terms, section 1.5** ([core.telegram.org/api/terms](https://core.telegram.org/api/terms)): "you are prohibited from using, accessing or aggregating data obtained from the Telegram platform to train, fine-tune or otherwise engage in the development, enhancement or deployment of artificial intelligence, machine learning models and similar technologies". Use is also subject to the Content Licensing and AI Scraping terms.
- **Content Licensing and AI Scraping** ([telegram.org/tos/content-licensing](https://telegram.org/tos/content-licensing)): "Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform" for those purposes. The only general licence is for data "strictly required" to operate a legitimate third-party client. The terms name no research or journalism exception.
- **What the integration does:** a collector and a watchlist index (harvesting and indexing channel media), SSCD embeddings over that media and model-based claim extraction from posts. That is the conduct the terms name. Breach notices give 10 days before API access is cut.
- **UK data protection:** the lawful basis would be legitimate interests with a documented balancing test. The ICO warns that "manifestly made public" is narrower than "publicly visible", and posts can carry special-category data. The journalism and research exemptions (Data Protection Act 2018, Schedule 2) were not confirmed for this use.

The options considered were to drop it, to allow manual import of a single public link only, or to build it behind a flag for local use. The third was chosen for a project that is not published or deployed. The terms above still apply to anyone who switches it on.

### How it works

- **The default collector is the public preview** (`t.me/s/<channel>`), the page any browser sees, read slowly (one request every few seconds). The Telethon collector is optional. It needs the user's own `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` and an interactive login, and the session file is never committed.
- **Public channels only**, named one by one on a watchlist. No groups, member lists or user profiles. Forward names that Telegram hides stay hidden.
- **The preview markup was checked against live pages on 2026-11-11**: post id, `<time datetime>`, the photo URL in a `background-image` style, and the "Forwarded from" link. A post's own page (`t.me/<channel>/<id>`) carries the photo as `og:image`, so the ordinary verifier fetches and checks every Telegram hit like any web page.

| Part | How it works |
| --- | --- |
| Watchlist index | `telegram_channels` and `telegram_posts` (pHash, PDQ, SSCD embedding with an HNSW index, post time, text, forward header, the photo stored as an artefact). `python -m origin_worker.telegram watch / list / collect / login`. Collection resumes from the newest post collected and skips photos already indexed. |
| Throttling | One request every `ORIGIN_TELEGRAM_INTERVAL_S` (default 3 s). A 429 is honoured for up to 60 s once. Longer waits stop that channel. Telethon sleeps through flood waits up to 60 s and raises above that. |
| Provider | `TelegramIndex` returns the 50 nearest posts by SSCD cosine (at least 0.5) plus any within pHash 8. Each hit's page is the post's own page, so the verifier decides. The adapter is `local`: the runner never caches, meters or replays it, because a cached answer would hide posts indexed since. |
| Dating | A Telegram hit's post time is a `platform` signal (exact bound, high confidence). |
| Targeted sweep | A stage after `date`. Keywords are the two most frequent content words in the verified pages' titles. Each watchlist channel is searched (`?q=`), photos posted from 30 days before to 1 day after the earliest web date are indexed, the index is queried again, and new hits are verified and dated. |
| Forward edges | The sweep follows the forward header of every verified Telegram post to a public source post (up to three hops), reading the source's time from its embed page, then verifies it. The branch stage records a `forward` propagation edge between the two sightings. |

## 8. Running cost

Zero. Vision stays under 950 units per month by hard stop. SerpApi stays under 250 searches per month (one per Lens trace; the image upload is not billed). Wayback and Telegram are free. The language model is the Gemini free tier, Ollama or recorded output. Hosting is local Docker Compose. Every response is cached by content hash, so re-runs spend nothing.

Accounts needed to run live traces, all on free tiers: a SerpApi key (Lens), a Google AI Studio key (Gemini) and, optionally, a Google Cloud project with the Vision API, a Cloudflare R2 bucket (for Yandex) and a dedicated Telegram `api_id` and `api_hash`.
