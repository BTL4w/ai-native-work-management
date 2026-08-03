SHELL := /bin/bash

PNPM := corepack pnpm@10
E2E_DB_NAME := work_management_e2e
E2E_DATABASE_URL := postgresql+psycopg://work_management:work_management@localhost:5432/$(E2E_DB_NAME)

.DEFAULT_GOAL := dev

.PHONY: dev up bootstrap install db-up backend-dev frontend-dev migrate seed down ai ai-sync ai-lint ai-typecheck ai-test containers-build containers-up containers-down containers-config-check ai-image-check lint typecheck test test-ai test-e2e e2e-db-reset migration-check

dev: bootstrap
	$(MAKE) --no-print-directory -j2 backend-dev frontend-dev

up: dev

bootstrap: install
	$(MAKE) --no-print-directory db-up
	$(MAKE) --no-print-directory migrate
	$(MAKE) --no-print-directory seed

install:
	$(MAKE) --no-print-directory -C backend sync
	$(PNPM) --dir frontend install --frozen-lockfile

db-up:
	docker compose up -d --wait --wait-timeout 60 postgres

backend-dev:
	$(MAKE) --no-print-directory -C backend up

frontend-dev:
	$(PNPM) --dir frontend dev

migrate:
	$(MAKE) --no-print-directory -C backend migrate

seed:
	$(MAKE) --no-print-directory -C backend seed

down:
	docker compose down

ai:
	$(MAKE) --no-print-directory -C ai check

ai-sync:
	$(MAKE) --no-print-directory -C ai sync

ai-lint:
	$(MAKE) --no-print-directory -C ai lint

ai-typecheck:
	$(MAKE) --no-print-directory -C ai typecheck

ai-test:
	$(MAKE) --no-print-directory -C ai test

containers-build:
	docker compose --profile tools build backend-api frontend ai-check

containers-up:
	docker compose up -d --build --wait --wait-timeout 60 postgres backend-api frontend

containers-down:
	docker compose --profile tools down

containers-config-check:
	docker compose --profile tools config --quiet

ai-image-check:
	docker compose --profile tools run --rm --build ai-check

lint:
	$(MAKE) --no-print-directory -C backend lint
	$(PNPM) --dir frontend lint

typecheck:
	$(MAKE) --no-print-directory -C backend typecheck
	$(PNPM) --dir frontend typecheck

test:
	$(MAKE) --no-print-directory -C backend test
	$(PNPM) --dir frontend test --pool=threads

test-ai: ai-test

e2e-db-reset: db-up
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U work_management -d postgres -c "DROP DATABASE IF EXISTS $(E2E_DB_NAME) WITH (FORCE);"
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U work_management -d postgres -c "CREATE DATABASE $(E2E_DB_NAME);"
	APP_DATABASE_URL=$(E2E_DATABASE_URL) $(MAKE) --no-print-directory -C backend migrate
	APP_DATABASE_URL=$(E2E_DATABASE_URL) $(MAKE) --no-print-directory -C backend seed

test-e2e: install e2e-db-reset
	API_ORIGIN=http://127.0.0.1:8100 NEXT_DIST_DIR=.next-e2e $(PNPM) --dir frontend build:e2e
	$(PNPM) --dir frontend test:e2e

migration-check: db-up
	$(MAKE) --no-print-directory -C backend migration-check
