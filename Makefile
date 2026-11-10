.DEFAULT_GOAL := help
WEB := apps/web
NPM := npm --prefix $(WEB)
COMPOSE := docker compose -f infra/compose.yaml

.PHONY: help install dev down logs migrate lint fmt test test-py test-web

help:
	$(info dev       Build and start the stack: db, redis, s3, api, web)
	$(info down      Stop the stack (data volumes are kept))
	$(info logs      Follow stack logs)
	$(info migrate   Apply database migrations to DATABASE_URL (default: compose db))
	$(info install   Install Python and web dependencies)
	$(info lint      ruff, pyright (strict), eslint, tsc)
	$(info fmt       Format Python sources)
	$(info test      pytest and Vitest)
	@:

dev:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

migrate:
	uv run python -m origin_core.db.migrate upgrade

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
