SHELL := /bin/bash

UV := uv

.DEFAULT_GOAL := check

.PHONY: sync lint format-check typecheck test check

sync:
	$(UV) sync --locked

lint:
	$(UV) run --locked ruff check src tests

format-check:
	$(UV) run --locked ruff format --check src tests

typecheck:
	$(UV) run --locked pyright

test:
	$(UV) run --locked pytest -m "not live_provider"

check: lint format-check typecheck test
