# Fixtures

Recorded real provider responses that let tests run with no keys and no network. Nothing hand-authored is kept here.

| Path | Contents |
| --- | --- |
| `recordings/<provider>/<request_hash>.json` | Real responses captured with `ORIGIN_PROVIDER_MODE=record` (`scripts/record_lens.py`, `scripts/record_wayback.py`). API keys found in the body are replaced with `[REDACTED]`. Each carries `"synthetic": false`. |
| `queries/earthrise.jpg` | The public-domain photograph the Lens recording was made with. |
| `c2pa/` | Test images and the published test-signing credentials used by the Content Credentials tests (see its README). |

In replay mode a query with no file for its request hash fails with an explicit error; it never returns an empty result.

Each file records the provider, the request hash, the query image's SHA-256, the parameters, when it was recorded, the content type, the units charged and the body with its SHA-256. The request hash is recomputed from the provider, image hash and parameters, so a file cannot be quietly reused for a different query.

Check every file:

```sh
uv run python -m origin_core.providers.fixtures verify
```

`make lint` and CI run the same check.
