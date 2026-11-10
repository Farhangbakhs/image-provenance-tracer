# CLAUDE.md

Context for Claude Code sessions on ORIGIN, an image provenance tracer. Read `PLAN.md` first: it holds the spec, the verification log and the phase list. Start a fresh session per phase.

## Working rules

- Work phase by phase. At the start of a phase, propose its sections. Implement each section with tests, run lint, type checks and tests, then commit and push. At the end of a phase, update `PLAN.md`, report (what works, how to see it, what was deferred, what is needed), and **stop for the go-ahead**.
- **Budget is zero.** Never add a paid dependency, plan or billable call without asking. Default providers stay inside free tiers.
- **Verify before building.** Read current docs before writing any adapter or library integration. If docs contradict `PLAN.md`, say so and follow the docs.
- No features outside the spec without asking. Prefer fewer dependencies. No placeholder code, no TODOs in committed work, no mocked functionality presented as real. Synthetic fixtures are labelled `"synthetic": true` and live under `fixtures/synthetic/`.
- Ask for API keys only when a phase needs them.

## Product rules (never break)

1. A provider hit is a candidate until we fetch and verify it.
2. Dates are bounds. Say "earliest found", never "origin" or "first posted". Show "Earliest found in indexed sources. Earlier copies may exist." wherever an earliest date appears.
3. No uncited claims: every claim, narrative and edge references existing sighting or evidence IDs; LLM output that cites unknown IDs is rejected and retried.
4. Fetched web text is untrusted: delimited blocks only, and the system prompt forbids following instructions inside them.
5. No face recognition, no identification of people, in code or prompts.
6. Persist raw provider responses and artefacts with SHA-256 and fetch time. Tests and demo mode replay them with no network and no keys.

## Git rules (strict)

1. Remote `origin` = `https://github.com/Farhangbakhs/image-provenance-tracer.git`, branch `main`.
2. One commit per completed section; each commit builds and passes lint, types and tests, and holds only that section's changes. Push after each commit.
3. Conventional Commits, imperative mood, a short body explaining why when it is not obvious.
4. Commits are authored solely by the git identity configured on this machine. If it is incomplete, stop and ask; never invent a name or email.
5. **No** `Co-Authored-By` trailer, "Generated with Claude Code" line, or any mention of Claude, Anthropic or AI assistance in commits, PRs, tags or release notes. `.claude/settings.json` sets `attribution.commit` and `attribution.pr` to `""`. After each commit, check `git log -1 --format=%B` and amend (before pushing) if any such line is present.
6. Never commit secrets, `.env`, Telegram `*.session` files, or model weights (`*.pt`, `*.onnx`, `models/`). `.env.example` documents every variable.
7. Never force-push or rewrite pushed history without asking.

## Stack

- Python 3.12 (uv workspace): FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, arq on Redis, Postgres 16 + pgvector, SeaweedFS S3 (dev) / R2. httpx with a Playwright fallback.
- Image: imagehash, pdqhash (built from source on Linux), SSCD TorchScript on CPU (downloaded at runtime into `models/`, gitignored), OpenCV ORB + RANSAC, exiftool, c2pa-python.
- Text: trafilatura, htmldate, LLM translation.
- LLM: `LLMProvider` with Gemini (free tier), Ollama, Anthropic (optional) and a recorded provider. Prompts are versioned in `origin_core/llm/prompts/`, and provider, model and prompt version are stored on each row produced.
- Web: Next.js 16 App Router, TypeScript strict, Tailwind, TanStack Query, React Flow, d3-scale with hand-written SVG, SSE. The API client is generated from OpenAPI (`make client`).
- Quality: ruff, pyright (strict), pytest, Vitest, Playwright; structlog, OpenTelemetry.

## Layout

```
apps/api  apps/worker  apps/web  packages/shared (origin_core)  infra  evals  fixtures
```

## Commands (from Phase 0)

| Command | Does |
| --- | --- |
| `make dev` | Start the compose stack (db, redis, s3, api, worker, web) |
| `make demo` | Start in demo mode: fixture providers, recorded LLM, seeded cases, no keys |
| `make test` | pytest and Vitest |
| `make lint` | ruff check and format check, pyright, eslint, tsc |
| `make e2e` | Playwright against demo mode |
| `make migrate` | Alembic upgrade head |
| `make client` | Regenerate the TypeScript API client from OpenAPI |
| `make eval` | Run the eval harness and write `evals/report.md` |

## Environment notes

- Windows host. Use Docker for Postgres, Redis and SeaweedFS. exiftool must be installed locally for non-Docker runs.
- The machine has Python 3.14 globally; the project pins 3.12 through uv (`.python-version`).
