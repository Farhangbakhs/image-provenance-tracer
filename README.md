# ORIGIN

An image provenance tracer for open-source intelligence work. Give it one image and it returns a dated, evidence-backed history: the earliest sighting found, every verified copy and edit, and the points where the story told about the image changes.

> Earliest found in indexed sources. Earlier copies may exist.

ORIGIN never reports an "origin". Private, deleted and unindexed posts are invisible to it, so every result is a bound, not a fact.

## Status

Under construction, phase by phase. See [PLAN.md](PLAN.md) for the specification, the verification log for every external service, and the phase list. Quick start, architecture, evaluation results and the ethics section are filled in as each phase lands.

## Development

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, Docker, GNU Make.

```sh
make install   # Python 3.12 venv and web dependencies
make lint      # ruff, pyright (strict), eslint, tsc
make test      # pytest and Vitest
```
