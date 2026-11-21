# ORIGIN: limitations

What ORIGIN does not do, what has not been verified, and where the tests use stand-in data. Design decisions are in [DESIGN.md](DESIGN.md).

## What a result means

- Every date is a bound. ORIGIN reports the earliest copy it found in indexed sources. Private, deleted and unindexed posts are invisible to it, so an earlier copy may exist.
- Most live copies are proven only by the time ORIGIN fetched them, so their position on the timeline is the earliest date their evidence allows, not a publication date.
- Relative provider dates ("9 days ago") are not parsed and stay undated. Absolute dates are.
- A trace verifies at most 50 provider hits, best-ranked first (`ORIGIN_VERIFY_MAX_CANDIDATES`). The rest are listed as not checked.
- Pages that a provider's redirect or the site's own blocking stops ORIGIN reaching are counted and listed. They are not verified.

## Known failure cases

- **Stereo pair false positive.** The matching eval's hardest negative is the same scene photographed from two slightly different positions (`motorcycle_left.png` and `motorcycle_right.png`). It is classified as a near-duplicate on a pHash distance of 4, and SSCD scores it 0.914. Two frames from one burst would look the same. A fix needs a signal that separates near-identical frames, such as dense pixel alignment after registration. It has not been attempted, because there are too few such pairs to test on. Source: `evals/report.md`.
- **Missed edited copies.** On thresholds v2, 236 of 252 edited copies are found (93.7%). The 16 misses are listed with their scores in `evals/report.md`. Seven are heavy crops with a caption (`small_crop_caption`), and the rest are mostly one low-texture image (`clock_motion.png`) that fails the geometric check.
- **Small eval images.** The 18 sample photographs are mostly 512 px or less, so recall on heavy crops is a floor. Real reposts start from larger originals.

## Not verified

- **Cloud Vision.** The adapter is written from the documentation. It has never run against the live API, so there is no Vision recording. The 1,000 free units a month were confirmed only from secondary sources, because the official pricing page did not render. Whether the API accepts a plain API key is also unconfirmed.
- **Yandex.** The adapter is written from the documentation. Whether Yandex through SerpApi accepts `image_id` is unconfirmed, so it needs a public URL and stays off by default.
- **Gemini free-tier rate limits** per model are not on the pricing page. They are read from the AI Studio rate-limit page once a key exists.
- **c2pa-python validation field names.** The mapping to the three trust states is tested against the fixtures and the installed version, not against a wide set of real-world signed images.
- **Telethon collector.** It needs a logged-in account and has not been run against Telegram. It is tested with a stand-in client written to Telethon 1.45's documented interface.
- **Quota periods.** Quota resets at UTC calendar boundaries. A vendor that resets on a billing anniversary will differ. The Vision hard stop at 950 units absorbs this.

## What is replayed or stand-in data

- The Lens and Wayback recordings in `fixtures/recordings/` are real responses (`"synthetic": false`). They cover one query image, the public-domain Apollo 8 "Earthrise" photograph: 391 exact matches, 316 of them dated, back to 24 December 2005 (`scripts/record_lens.py`).
- The Telegram tests use generated data and are labelled `SYNTHETIC` in their headers: channel pages in the `t.me/s` markup, hand-made vectors and hashes for the index, and a stand-in web page, preview, post page and photo host for the end-to-end trace. No real Telegram traffic is recorded.
- The matching eval uses scikit-image sample photographs with edits applied by `evals/matching.py`.
- There is no demo mode and no seeded case data. A trace needs real keys (see the README).

## Telegram

- The terms analysis in [DESIGN.md](DESIGN.md#7-telegram-integration) concludes that bulk collection and indexing conflict with Telegram's API and content-licensing terms. The integration is for local research, is off by default, and is refused in production. Anyone who enables it is responsible for complying with those terms and with data protection law.
- Coverage is the watchlist. No Telegram hit means "not in the channels ORIGIN indexes".
- Albums are indexed photo by photo, but a post's own page shows only its first photo, so later album photos verify only when the verifier finds them on that page.
- Forward names that Telegram hides stay hidden.

## Operational limits

- **Cold start.** With images built, `make dev` is ready in about a minute. The first build downloads CPU PyTorch and the SSCD weights (about 2 GB) and can take more than five minutes on a slow connection. Prebuilt images are not published.
- **Image size.** The Python image is about 2.1 GB. A slim API-only image has not been built.
- **pdqhash** has no Linux wheels, so the Docker build compiles it.
- **Not built:** the investigator agent. The matching eval, rate limits and end-to-end tests exist.
- **Licensing before any public deployment.** The SSCD maintainers state that the weights are MIT, but the weights' own README states no licence. Review this before redistributing or hosting the model.
