SHELL := /bin/bash

UV := uv

.DEFAULT_GOAL := up

.PHONY: up dev sync migrate seed lint format-check typecheck test test-integration migration-check

up: sync
	$(UV) run fastapi dev app/main.py

dev: up

sync:
	$(UV) sync --locked

migrate: sync
	$(UV) run alembic upgrade head

seed: sync
	APP_DEMO_SEED_ENABLED=true $(UV) run python -m app.scripts.seed_demo

lint:
	$(UV) run ruff check app tests alembic

format-check:
	$(UV) run ruff format --check app tests alembic

typecheck:
	$(UV) run pyright

test:
	$(UV) run pytest -m "not integration"

test-integration:
	RUN_POSTGRES_INTEGRATION=1 $(UV) run pytest -m integration

migration-check: migrate
	$(UV) run alembic current --check-heads
	$(UV) run alembic check
	$(MAKE) test-integration
