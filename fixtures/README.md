# Fixtures

Recorded provider responses that let tests and demo mode run with no keys and no network.

| Directory | Contents | `synthetic` |
| --- | --- | --- |
| `recordings/<provider>/<request_hash>.json` | Real responses captured with `ORIGIN_PROVIDER_MODE=record`. API keys found in the body are replaced with `[REDACTED]`. | `false` |
| `synthetic/<provider>/<request_hash>.json` | Hand-authored responses, used only where no real recording exists yet. | `true` |
| `cases/` | Seeded demo cases (from Phase 4). | — |

In replay mode recordings are read before synthetic files, so a real recording always replaces a synthetic one. A query with no file for its request hash fails with an explicit error; it never returns an empty result.

Each file records the provider, the request hash, the query image's SHA-256, the parameters, when it was recorded, the content type, the units charged and the body with its SHA-256. The request hash is recomputed from the provider, image hash and parameters, so a file cannot be quietly reused for a different query.

Check every file:

```sh
uv run python -m origin_core.providers.fixtures verify
```

`make lint` and CI run the same check.
