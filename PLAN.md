# ORIGIN: plan

ORIGIN is an image provenance tracer for open-source intelligence work. An analyst uploads one image. ORIGIN finds where the image has appeared online and proves that each appearance is the same picture or a derivative. It dates each appearance with explicit uncertainty and shows where the story told about the image diverges. Every statement in the output cites a stored piece of evidence.

This file refines the original build brief. Section 1 records what was checked against live documentation on 2026-11-10 and what changed as a result. The rest is the specification the phases build against.

---

## 1. Verification log (2026-11-10)

### 1.1 Confirmed or corrected

| Item | Brief said | Found | Source | Effect |
| --- | --- | --- | --- | --- |
| SerpApi free plan | 250 searches/month, 50/hour | **Confirmed.** 250/month, 50/hour throughput. Only successful searches count. | [serpapi.com/pricing](https://serpapi.com/pricing) | Quota meter defaults: `serpapi` 250/month, 50/hour. |
| SerpApi Google Lens input | Needs a public URL, so a presigned link | **Corrected.** Lens takes `url` **or** `image_id`. The Image API (`POST https://serpapi.com/image`, multipart field `image`) returns an `image_id` that expires after 10 minutes. Limits: JPG, PNG or WebP, **≤ 500 KB**. Announced in SerpApi's changelog for 3–9 August 2026. | [serpapi.com/image-api](https://serpapi.com/image-api), [Lens upload guide](https://serpapi.com/google-lens-upload-an-image), [Lens API](https://serpapi.com/google-lens-api) | The Lens adapter uploads bytes and needs no public URL. Images over 500 KB get a re-encoded copy, max 1600 px long edge with JPEG quality stepped down until ≤ 500 KB; the copy is stored, hashed and logged. |
| SerpApi Lens `type` | Exact and visual matches | **Confirmed.** `type` = `all`, `exact_matches` or `visual_matches`. Visual match fields: `position, title, link, source, thumbnail, image, image_width, image_height`. The exact-match response shape is not fully documented. | [Lens API](https://serpapi.com/google-lens-api) | One `exact_matches` call per trace by default (1 search). The adapter contract tests are written from the first real recorded response, not from memory. |
| SerpApi Yandex | Same URL requirement | **Confirmed URL-only.** `engine=yandex_images&url=…`. `image_id` support is **not documented** for Yandex. Results: `images_results[]` (`link, source, original, title, snippet, thumbnail, size`); `tab=similar` gives `similar_images`. | [Yandex Images API](https://serpapi.com/yandex-images-api) | Yandex still needs a short-lived public URL. The local object store is not public, so Yandex is **off by default** until a public object store (Cloudflare R2 free tier) or a confirmed `image_id` route exists. "Local providers only" mode excludes it. |
| Google Cloud Vision web detection | First 1,000 units/month free, billing account needed | **Confirmed, from secondary sources.** The first 1,000 units/month are free; Web Detection then costs $3.50 per 1,000. A billing account is required. The official page did not render in the fetch tool. | [cloud.google.com/vision/pricing](https://cloud.google.com/vision/pricing), [vantaige.io summary](https://vantaige.io/blog/google-vision-ai-pricing-explained-alternatives-2026) | Quota meter default: 1,000 units/month with a **hard stop at 950**, so a miscount cannot bill. Open item for you: confirm on the console's billing page. |
| Vision request shape | Accepts bytes | **Confirmed.** `POST https://vision.googleapis.com/v1/images:annotate`, `image.content` = base64, `features[{type: WEB_DETECTION, maxResults}]`. Response: `fullMatchingImages`, `partialMatchingImages`, `pagesWithMatchingImages{url,pageTitle,fullMatchingImages,partialMatchingImages}`, `visuallySimilarImages`, `webEntities`, `bestGuessLabels`. Docs show OAuth or ADC auth; an API key restricted to the Vision API also works on `?key=` (to confirm when you create the key). | [detecting-web](https://docs.cloud.google.com/vision/docs/detecting-web) | Adapter auth: API key first, service account JSON as fallback. |
| SSCD | Confirm the weight licence | **Code is MIT. The README states no licence for the weights.** TorchScript files are at `dl.fbaipublicfiles.com/sscd-copy-detection/`, e.g. `sscd_disc_mixup.torchscript.pt`. Preprocessing: RGB, `Resize(288)` (small edge) or `Resize([320,320])`, ImageNet mean/std. Output is a 512-d L2-normalised vector (1024-d for `disc_large`). | [facebookresearch/sscd-copy-detection](https://github.com/facebookresearch/sscd-copy-detection) | Weights are **downloaded at runtime, never committed or redistributed**, and the model is used only for local inference. The licence question stays open before any public deployment (section 1.3). |
| pdqhash | — | v0.2.8, MIT bindings; the PDQ source carries its own licence. Wheels exist for CPython 3.10–3.13 on Windows and macOS only. **No Linux wheels.** API: `compute(img) -> (vector, quality)`, `compute_dihedral` gives 8 variants. | [pypi.org/project/pdqhash](https://pypi.org/project/pdqhash/) | Docker images need a C++ toolchain to build pdqhash. We stay on Python 3.12, not the 3.14 installed on this machine. `compute_dihedral` also gives a cheap mirror/rotation check. |
| c2pa-python | Three trust states | v0.38.2, MIT/Apache-2.0, Python ≥ 3.10. `with Reader(path, context=ctx) as r: r.json()`. Trust anchors are set via `Settings.from_dict({"verify":{"verify_cert_anchors":True},"trust":{"trust_anchors":pem}})`. The report carries `validation_status` when there are errors. | [c2pa-python](https://github.com/contentauth/c2pa-python), [usage.md](https://github.com/contentauth/c2pa-python/blob/main/docs/usage.md) | ORIGIN maps the report to `none`, `present_untrusted` or `valid_trusted`. Exact field names (`validation_state` vs `validation_status`) are confirmed against the installed version and a real sample in Phase 1. |
| Wayback CDX | Free, keyless, rate-limited | **Confirmed API.** `GET http://web.archive.org/cdx/search/cdx?url=…&output=json&limit=1&fl=timestamp,original,statuscode,digest`. Results sort by URL, then time. | [wayback-cdx-server](https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server) | Earliest capture = `limit=1`, exact match. One request per second, exponential backoff, cached forever (a first capture never changes). |
| PicImageSearch | MIT, unofficial | **Confirmed.** v3.12.11, MIT, Python ≥ 3.9. | [PyPI JSON](https://pypi.org/pypi/PicImageSearch/json) | Stays opt-in, local-only, behind `ORIGIN_ENABLE_UNOFFICIAL_PROVIDERS=true`; refused at startup when `ORIGIN_ENV=production`. |
| Hosted free LLM tier | Pick one and present options | Gemini API free tier covers 2.5 Flash, 2.5 Flash-Lite, 2.5 Pro and the 3.x Flash/Flash-Lite models. **Free-tier prompts and outputs are used to improve Google's products.** Per-model free rate limits are not on the pricing page. | [aistudio.google.com/docs/pricing](https://aistudio.google.com/docs/pricing) | See the options in 1.4. Whatever you pick, fetched page text sent to a free tier is public web content, but you should know the vendor keeps it. |
| Claude Code attribution setting | Find the setting | `attribution` object: `commit: ""`, `pr: ""`, `sessionUrl: false`. A bare `attribution: false` needs v2.1.281+; the object form works on all versions. | [settings reference](https://code.claude.com/docs/en/settings-reference.md#attribution) | Written to `.claude/settings.json` (committed, so it travels with the repo). |
| Local object storage | MinIO | **Corrected.** MinIO stopped publishing community Docker images (`minio/minio` now 404s on Docker Hub; the quay.io mirror is frozen at a 2025 release with an unpatched CVE). | [MinIO archived: alternatives](https://pinggy.io/blog/minio_archived_self_hosted_s3_alternatives/), `docker manifest inspect minio/minio` | Development uses **SeaweedFS 4.51** (Apache-2.0) with its S3 gateway on port 8333. The app only speaks the S3 API, so R2 is unchanged for deployment. |
| Package currency | — | FastAPI 0.162.4, arq 0.28.0, Telethon 1.45.0, trafilatura 2.3.1, htmldate 1.11.0, pgvector 0.5.1, opencv-python-headless 5.0.0.93, torch 2.15.0 (Python ≥ 3.11), ImageHash 4.3.2, Next.js 16.4.6. | PyPI and npm registries | These are pinned in lock files; uv and npm resolve them at Phase 0. |

### 1.2 Contradictions with the brief

1. **Lens no longer needs a public URL.** This removes the main privacy cost for Lens. Yandex still needs one.
2. **Yandex cannot run in pure local development** without a public object store. It is off by default; enabling it requires `S3_PUBLIC_ENDPOINT` (R2) and is listed in the upload disclosure.
3. **pdqhash has no Linux wheels**, so the Docker images include a build stage.

### 1.3 Assumptions I could not confirm

- ~~The SSCD weight licence~~ **Resolved (Phase 1):** the maintainers state that the whole project, weights included, is MIT ([issue #12](https://github.com/facebookresearch/sscd-copy-detection/issues/12)).
- The official Cloud Vision pricing page did not render; the 1,000 free units are confirmed only via Google-hosted localised pages in search snippets and a third-party summary.
- ~~Whether a SerpApi Image API upload counts as a search.~~ **Measured 2026-11-11: it does not.** One upload plus one Lens search moved `this_month_usage` from 0 to 1 (`/account.json`). The meter charges 1 unit per Lens trace.
- Whether Yandex via SerpApi accepts `image_id`.
- Gemini **free-tier rate limits** per model (not on the pricing page; read from AI Studio's rate-limit page after you create a key).
- The exact **c2pa-python validation field names** in v0.38.
- The Vision API accepting a plain **API key** (standard for Vision; confirmed once your key exists).
- ~~Telegram API terms and UK data-protection duties~~ **Checked (2026-11-11): Phase 5 is blocked pending your decision.** See 1.9.
- **Aside** is not among this session's tools, so the normal web tools were used.

### 1.4 LLM options (decided: A is the default)

| Option | Cost | Trade-off |
| --- | --- | --- |
| **A. Gemini 2.5 Flash, free tier** (chosen default, 2026-11-10) | Free | Strong structured JSON output, multilingual (needed for translation). Free-tier data is used by Google to improve products; rate limits are modest. |
| B. Ollama with a local model (e.g. Qwen 3 8B or Llama 3.x 8B) | Free | Fully private and offline. Slower on CPU, weaker extraction quality; you need about 8 GB of RAM free. |
| C. Anthropic Claude | Paid key | Best quality; used only if `ANTHROPIC_API_KEY` is set. |

All three sit behind one `LLMProvider` interface. Demo mode and tests use recorded outputs and need none of them.

### 1.5 Accounts and keys you need (all free)

| Needed for | Account | What to create | When |
| --- | --- | --- | --- |
| Lens (and Yandex) | serpapi.com | Free plan API key | Phase 2 |
| Vision web detection | Google Cloud | Project, billing account (no charge within the free tier), enable the Cloud Vision API, API key restricted to Vision. Optionally set a budget alert at £1. | Phase 2 |
| Hosted LLM (if option A) | Google AI Studio | Gemini API key | Phase 3 |
| Public object store for Yandex (optional) | Cloudflare | R2 bucket and S3 token (free tier) | Phase 2 or later |
| Telegram | my.telegram.org | `api_id` and `api_hash` on a **dedicated** account, not your personal one | Phase 5 |
| CI | GitHub | Already have the repo; Actions free tier | Phase 0 (done) |

Local tools to install: **exiftool** (not on this machine). Python 3.12 is installed by `uv` automatically. Docker, Node and `uv` are already present.

### 1.6 Decisions made while building Phase 0

| Decision | Why |
| --- | --- |
| **SeaweedFS** replaces MinIO for local object storage | MinIO's community images are gone (1.1). The app speaks plain S3, so nothing else changes. |
| **Provider response cache is durable**: stored raw responses (`provider_calls` + artefacts), not Redis | A cache hit then survives restarts and is itself evidence; Redis keeps only jobs and run events. |
| **Run events use Redis Streams**, not pub/sub | Late or reconnecting browsers resume from `Last-Event-ID` without missing a stage. |
| **Migrations ship inside `origin_core`** (`python -m origin_core.db.migrate`) | The container image can migrate itself; no `alembic.ini` to keep in sync. |
| **`propagation_edges` table** alongside `variant_edges` | Forwards and credits link *sightings*; derivations link *variants*. One table would leave half its columns empty. |
| **Integrity rules enforced in Postgres** | Claims need a sighting (FK); narratives need a claim (deferred constraint trigger); `audit_events` rejects UPDATE, DELETE and TRUNCATE; quota cannot exceed its limit; date intervals are ordered. |
| **Replay mode fails loudly** on a missing recording | An empty result would read as "no matches found", which is a false finding. |
| **Quota periods align to UTC calendar boundaries** | Vendors may reset on a billing anniversary instead; the Vision hard stop at 950 absorbs that mismatch. |
| **Local `make` caveat** | The `make` first on this machine's PATH comes from GAMS and cannot run recipes that need a shell. Use a standard GNU make (e.g. `winget install ezwinports.make`) or run the commands directly. |

### 1.7 Decisions made while building Phase 1

| Decision | Why |
| --- | --- |
| **Ingest is split between API and worker** | Validation, storage, hashes, exiftool and C2PA run at upload so a bad file is refused at the door; the SSCD embedding runs in the worker's ingest stage, so only the worker loads PyTorch. |
| **c2pa-python pinned to 0.38.0** | 0.38.1 and 0.38.2 were published with macOS wheels only. |
| **Official C2PA trust list vendored and hash-checked** | From `c2pa-org/conformance-public` at commit `64b3f9c` (CC-BY-4.0). Every C2PA result records the list it was judged against. |
| **Invalid manifests stay distinguishable** | The schema has three states, but the raw validation state and failure codes are stored and shown, so "Invalid" never reads as merely "untrusted". |
| **Metadata never invents certainty** | A capture time without a zone offset is shown as stated, never as UTC; GPS without a hemisphere is left unknown. exiftool failing is "unavailable", not "no metadata". |
| **CPU-only PyTorch from the PyTorch index** | The default Linux wheels bundle ~2.5 GB of CUDA. The Python image is still 2.1 GB; a slim API-only image is a later optimisation. |
| **Model weights downloaded, verified, never committed** | `python -m origin_worker.embedding download`; SHA-256 pinned; tests never download (CI fetches in a setup step and requires the model). |
| **Worker health check reads arq's heartbeat key** | `arq --check` imports PyTorch and outlasts the check timeout; the heartbeat refreshes every 30 s. |
| **Local CI (`make ci`)** | GitHub Actions is unavailable on this account (billing lock). `make ci` runs the same jobs in Linux containers against committed HEAD. |
| **Dating vocabulary extended (Phase 2)** | `no_earlier_than` (capture or signing time floors a sighting) and `observed` (ORIGIN's own fetch caps it) were needed by the dating rule. |

### 1.8 Decisions made while building Phases 2 to 4

| Decision | Why |
| --- | --- |
| **Thresholds v2: a geometric route to "derivative"** | A real crop-and-caption copy scored SSCD 0.69, below v1's derivative cut. v2 also accepts SSCD ≥ 0.5 when ORB + RANSAC finds ≥ 60 inliers. Every sighting stores the threshold version it was judged by. |
| **The fetcher pins the vetted IP** | DNS is resolved once, every address must be global, and the connection goes to that address with SNI set, so a rebinding answer cannot redirect it. Redirects are re-vetted hop by hop. |
| **Gemini model `gemini-3.5-flash-lite`** | `gemini-2.5-flash` is closed to new free-tier keys; `3.8-flash` answered too slowly on the free tier for claim extraction. |
| **Only a contradiction opens a branch** | When the model groups claims apart without marking a contradiction, the groups join the root narrative. The model judges contradiction; the root is decided by the evidence (the earliest-dated claim). |
| **Demo web is synthetic, the pipeline is not** | Demo pages, `.example` domains, archive dates and the reverse-image index are declared in `fixtures/demo/cases.json` and labelled synthetic. Every stage runs for real over them, and the model's answers were recorded once and replay with no key. |
| **Brief is a print stylesheet, not WeasyPrint** | The brief page renders the evidence pack and prints to PDF from any browser; Playwright's `page.pdf()` checks it in the e2e suite. No extra Python dependency or system libraries. |
| **Evidence pack format `origin.evidence-pack.v1`** | One JSON document: findings, provider calls, audit trail, and every artefact with SHA-256, fetch time and storage key. |

Open items from Phases 2 to 4:

- **Live provider check (Lens done 2026-11-11).** `scripts/record_lens.py` ran a live Lens exact-matches query for the public-domain Apollo 8 "Earthrise" photograph (`fixtures/queries/earthrise.jpg`). SerpApi returned 391 exact matches, 316 of them dated, back to 24 Dec 2005. The recording is in `fixtures/recordings/lens/`, and `test_lens_contract.py` runs the adapter against it offline. Every absolute date parsed; relative ones ("9 days ago") stay unparsed. Vision stays unrecorded: no Vision key, by choice.
- **Stereo-pair false positive.** The eval's hardest negative (the same scene from a slightly different position) is classified near-duplicate on pHash 4, and SSCD scores it 0.914. Two frames from one burst would look the same. A fix needs a signal that tells near-identical frames apart (dense pixel alignment after registration); not attempted without more such pairs to test on.
- **Cold demo time.** With images built, `make demo` is ready in about a minute. The first build downloads CPU PyTorch and the SSCD weights (about 2 GB) and takes longer than five minutes on a slow connection; publishing prebuilt images is a Phase 6 item.

### 1.9 Telegram (Phase 5): terms check, 2026-11-11

Phase 5 was not built. The terms that apply to it conflict with the planned design.

- **API Terms, section 1.5** ([core.telegram.org/api/terms](https://core.telegram.org/api/terms)): "you are prohibited from using, accessing or aggregating data obtained from the Telegram platform to train, fine-tune or otherwise engage in the development, enhancement or deployment of artificial intelligence, machine learning models and similar technologies", and use is further subject to the Content Licensing and AI Scraping terms.
- **Content Licensing and AI Scraping** ([telegram.org/tos/content-licensing](https://telegram.org/tos/content-licensing)): "Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform" for those purposes. The only general licence is the data "strictly required" to operate a legitimate third-party client. The terms name no research, journalism or search exception.
- **What Phase 5 would do:** a collector and a *watchlist index* (harvesting and indexing channel media), SSCD embeddings over that media and LLM claim extraction from posts (deploying ML models on Telegram data). That is the conduct the terms name. Breach notices give 10 days before API access is cut.
- **UK data protection:** the lawful basis would be legitimate interests with a documented balancing test. The ICO warns that "manifestly made public" is narrower than "publicly visible", and posts can carry special-category data. The journalism and research exemptions (DPA 2018, Schedule 2) were not confirmed for this use.

Options for you to choose from:

1. **Drop Phase 5.** The web pipeline is unaffected.
2. **Manual import only.** The analyst pastes a public `t.me/<channel>/<id>` link. ORIGIN fetches the public web preview (`t.me/s/…`), the same page any browser sees, as a web sighting. No API account, no index, no bulk collection. This still runs ORIGIN's matching over the image, so read the terms yourself before relying on it.
3. **Build as specified behind the flag, off by default, for your own legal review.** Not recommended without advice.


---

## 2. Principles

1. A provider hit is a **candidate**. It becomes a **sighting** only after we fetch the image and verify it ourselves.
2. Dates are **bounds**. Each timestamp signal is stored separately with kind, bound type (`exact`, `no_later_than`, `claimed`) and confidence. The product says "earliest found", never "origin" or "first posted".
3. **No uncited claims.** Claims, narratives and edges reference existing sighting and evidence IDs. The schema enforces this, and LLM output that cites unknown IDs is rejected and retried.
4. Fetched web content is **untrusted data**. It goes to models only inside delimited blocks, under a system prompt that forbids following instructions inside them.
5. **No face recognition and no identification of people.**
6. **Everything is replayable.** Raw provider responses and fetched artefacts are stored with SHA-256 and fetch time.
7. **Verify before building.** Adapters are written from current docs and recorded responses.

Every screen and export that shows an earliest date also shows: **"Earliest found in indexed sources. Earlier copies may exist."**

---

## 3. Architecture

```
apps/web (Next.js 16, App Router)  ──HTTP/SSE──▶  apps/api (FastAPI)
                                                       │ enqueue (arq)    ▲ progress (Redis Streams)
                                                       ▼                  │
                                                 apps/worker (arq) ───────┘
                                                       │
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
fixtures        recorded provider/LLM/fetch responses, seeded demo cases
```

One Python workspace (uv) holds `origin_core`, `api` and `worker`. The API and worker share models and the database layer through `origin_core`.

---

## 4. Pipeline

Each stage is idempotent and resumable, and records start, end, counts, quota used and errors on `runs.stages` (JSON per stage). Each stage reads only from the database and object store, so any stage can be re-run alone.

1. **Ingest.** Check magic bytes (JPEG, PNG, WebP, GIF first frame, HEIC if libheif is present). Caps: 20 MB and 50 MP. Store the original untouched and a re-encoded display copy. Compute SHA-256, pHash and dHash (imagehash), PDQ and quality, PDQ dihedral, and the SSCD embedding. Extract EXIF, XMP and IPTC with `exiftool -j -G1`. Read C2PA and record `none`, `present_untrusted` or `valid_trusted` plus the raw report.
2. **Discover.** Fan out through `ProviderAdapter`:
   ```python
   class ProviderAdapter(Protocol):
       name: str; unit_cost: int; requires_public_url: bool; sends_bytes_to: str
       async def search(self, asset: AssetRef, ctx: ProviderContext) -> ProviderResult  # candidates + raw + units
   ```
   Defaults: `vision` (bytes) and `lens` (bytes via `image_id`). Optional: `yandex` (public URL), `tineye` (paid key), `unofficial` (PicImageSearch; local only, gated), `fixture` (replay), and `telegram` (Phase 5). Each adapter call goes through a wrapper that handles timeout, retry with jittered backoff, a circuit breaker, the quota check-and-debit, and a response cache keyed by `(provider, sha256, params_hash)`.
3. **Verify.** One hardened fetcher fetches each candidate image and page. Classification, with thresholds in `matching/thresholds.v1.toml`:
   - `exact`: equal SHA-256
   - `near_duplicate`: pHash Hamming ≤ 8 or PDQ ≤ 31 (or any PDQ dihedral ≤ 31 → mirror/rotation flag)
   - `derivative`: SSCD cosine ≥ 0.75 **and** ORB+RANSAC homography with ≥ 15 inliers; records crop box, mirror flag, scale and overlay likelihood (from the residual difference outside matched regions)
   - otherwise `unrelated` (dropped, kept in `candidates` with the reason)
   The threshold version is stored on every sighting.
4. **Date.** Signals: platform timestamp, C2PA signed time, Wayback first capture (page URL and image URL), provider crawl date, page metadata (htmldate plus `article:published_time` and JSON-LD), HTTP `Last-Modified`, EXIF `DateTimeOriginal`. Reduction rule (`dating/rule.py`, v1, unit-tested):
   - `exact` signals with high confidence define the point; with several, take the earliest and flag a conflict if they differ by more than 24 h.
   - `no_later_than` signals set the interval's upper bound (the minimum of them).
   - `claimed` signals (page metadata, EXIF, Last-Modified) can narrow the interval only when they sit below the upper bound, and they cap the confidence at medium.
   - The lower bound is the latest of: the earliest claimed date that is consistent with the upper bound, the C2PA time, or "unknown" (open interval).
   - Confidence is the highest confidence among the signals that actually set a bound. The deciding signal is stored.
5. **Branch.**
   (a) Variants: union-find over pairwise near-duplicate links. Derived-from edges come from containment (a crop is a child of the wider frame), resolution (lower from higher), and overlay (captioned from clean); time only breaks ties. Each edge stores its reason code and evidence.
   (b) Claims: the LLM extracts `{event, place, date, actor_role, stance, quote_start, quote_end, language, translation}` per sighting. Output must validate against a JSON schema, the quote must be an exact substring of the delimited source text, and `sighting_id` must exist. On failure it retries up to twice, then records an extraction failure. `actor_role` describes roles ("protesters", "army"), never named private individuals.
   (c) Narratives: the earliest-dated claim seeds the root narrative. Each later claim is compared to every narrative on event, place and date (LLM judgement with cited IDs, plus deterministic checks on normalised place and date). A contradiction opens a new branch whose divergence sighting is the earliest claim in it.
   (d) Grading on the Admiralty scale. Reliability A–F comes from `sources` (seeded list plus a default of F, "cannot be judged"). Credibility 1–6 per sighting is computed from match class, the number of independent dating signals, archive presence and agreement with the earliest narrative. The rationale is stored as text.
6. **Report.** Timeline, graph and evidence-pack API; JSON export (every artefact with SHA-256, fetch time and storage key) and a PDF brief (WeasyPrint, or a print stylesheet rendered by Playwright).

---

## 5. Data model

UUID primary keys and `timestamptz` (UTC) throughout. Tables: `cases`, `assets`, `runs`, `provider_calls`, `provider_quota`, `candidates`, `sightings`, `timestamp_evidence`, `variants`, `variant_edges`, `claims`, `narratives`, `narrative_claims`, `sources`, `audit_events`, `artefacts` (content-addressed store index).

Rules the schema enforces:

- `claims.sighting_id NOT NULL` with an FK. `narratives` are inserted only together with at least one `narrative_claims` row (deferred constraint trigger).
- `audit_events` is append-only: a trigger rejects UPDATE and DELETE.
- `sightings.embedding vector(512)` with an HNSW index (`vector_cosine_ops`).
- Every `artefacts` row has `sha256`, `fetched_at`, `source_url`, `content_type` and `byte_size`.
- `provider_quota(provider, period_start, period_kind, limit, used)` with a row-locked debit.

---

## 6. Interface

An analyst console: dark, dense and quiet.

- **Tokens.** Graphite background `#0E0F11`, surface 1 `#15171A`, surface 2 `#1C1F23`, hairline `#2A2E34`. Text `#E6E8EB` and muted `#9AA1AB`. Amber accent `#F2A93B`, used **only** for "earliest known". Confidence colours: high `#4FB477`, medium `#C9B458`, low `#C96A5A`.
- **Type.** Inter for interface text, JetBrains Mono for hashes, URLs, timestamps and IDs. Tabular numerals; all times in UTC with a trailing `Z`.
- **Shape.** 2px radius at most. No shadows, gradients or glass.
- **Screens.** Intake; run monitor; case workspace with Timeline, Graph and Evidence views; evidence drawer; asset panel; export.
- **Keyboard.** `⌘K`/`Ctrl+K` palette, `j`/`k` through sightings, `e` opens evidence, `g` cycles views.

---

## 7. Phases

| Phase | Sections (proposed in full at the start of each phase) | Done when |
| --- | --- | --- |
| 0. Foundations **(done)** | repo skeleton and tooling; compose stack; schema and migrations; provider protocol, runner and quota; fixture recorder and replayer; pipeline runner, worker and SSE; CI | `make dev` starts everything; CI green on an empty pipeline |
| 1. Ingest **(done)** | upload validation; storage; hashing and embedding; metadata and C2PA; asset panel | an upload shows its asset panel; a C2PA sample reports the right state |
| 2. Discover, verify, date **(done)** | hardened fetcher; Vision adapter; Lens adapter; Yandex adapter; verification; dating rule; Wayback; flat list UI | a known viral image returns a verified, dated list that replays offline |
| 3. Branching **(done)** | variants and edges; LLM providers; claim extraction; narratives; grading | the seeded miscaptioned case shows ≥ 2 branches with the right divergence sighting |
| 4. Console **(done)** | timeline; graph; evidence drawer; run monitor; exports; demo mode with three seeded cases; Playwright | a cold reviewer runs the demo with no keys in under five minutes |
| 5. Telegram (flagged) **(blocked: see 1.9)** | collector; watchlist index; adapter; targeted sweep; preview fallback; forward edges | a seeded case surfaces a Telegram sighting earlier than any web sighting |
| 6. Agent, evals, hardening | eval set and harness; investigator agent; rate limiting and tracing; deployment config | eval report from one command; public demo |

If time runs short, cut the Phase 6 agent first and keep the evals.

---

## 8. Running cost

Zero. Vision stays under 950 units per month by hard stop. SerpApi stays under 250 searches per month (one per Lens trace; the image upload is not billed). Wayback and Telegram are free. The LLM is the Gemini free tier, Ollama or recorded output. Hosting is local Docker Compose plus demo mode. Every response is cached by content hash, so re-runs spend nothing.
