.DEFAULT_GOAL := help
WEB := apps/web
NPM := npm --prefix $(WEB)

.PHONY: help install lint fmt test test-py test-web

help:
	$(info install   Install Python and web dependencies)
	$(info lint      ruff, pyright (strict), eslint, tsc)
	$(info fmt       Format Python sources)
	$(info test      pytest and Vitest)
	@:

install:
	uv sync
	$(NPM) ci

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
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
