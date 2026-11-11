.DEFAULT_GOAL := help
WEB := apps/web
NPM := npm --prefix $(WEB)
# Docker Desktop ships an extensionless `docker` script next to docker.exe; Windows make finds
# the script first and cannot run it.
ifeq ($(OS),Windows_NT)
DOCKER := docker.exe
else
DOCKER := docker
endif
COMPOSE := $(DOCKER) compose -f infra/compose.yaml

.PHONY: help install dev demo e2e eval down logs migrate client lint fmt test test-py test-web ci

help:
	$(info dev       Build and start the stack: db, redis, s3, api, web)
	$(info demo      Start in demo mode (replayed providers, no keys) and seed the demo cases)
	$(info e2e       Playwright end-to-end tests against the running demo (make demo first))
	$(info eval      Run the eval harness and write evals/report.md)
	$(info down      Stop the stack (data volumes are kept))
	$(info logs      Follow stack logs)
	$(info migrate   Apply database migrations to DATABASE_URL (default: compose db))
	$(info client    Regenerate the typed web API client from the OpenAPI schema)
	$(info install   Install Python and web dependencies)
	$(info lint      ruff, pyright (strict), eslint, tsc)
	$(info fmt       Format Python sources)
	$(info test      pytest and Vitest)
	$(info ci        Run the CI jobs locally in Linux containers against committed HEAD)
	@:

dev:
	$(COMPOSE) up -d --build --wait

# Replay mode: every provider and model answer comes from fixtures/, so no keys are needed.
demo: export ORIGIN_ENV := demo
demo: export ORIGIN_PROVIDER_MODE := replay
# The demo's Telegram case is synthetic and offline, so the demo shows it.
demo: export ORIGIN_ENABLE_TELEGRAM := true
demo:
	$(COMPOSE) up -d --build --wait
	$(COMPOSE) exec -T worker python -m origin_worker.demo seed
	@echo Demo ready: open http://localhost:3000

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	uv run python -m origin_core.db.migrate upgrade

client:
	uv run python -m origin_api.openapi apps/web/openapi.json
	$(NPM) run gen:api

install:
	uv sync
	$(NPM) ci

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run python -m origin_core.providers.fixtures verify
	$(NPM) run lint
	$(NPM) run typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test: test-py test-web

test-py:
	uv run pytest -q

test-web:
	$(NPM) test

e2e:
	$(NPM) run e2e

eval:
	uv run --group eval python -m evals.run

ci:
	uv run python scripts/ci_local.py
