SHELL := /bin/bash

PNPM := corepack pnpm@10

.DEFAULT_GOAL := dev

.PHONY: dev up bootstrap install db-up backend-dev frontend-dev migrate seed down lint typecheck test migration-check

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

lint:
	$(MAKE) --no-print-directory -C backend lint
	$(PNPM) --dir frontend lint

typecheck:
	$(MAKE) --no-print-directory -C backend typecheck
	$(PNPM) --dir frontend typecheck

test:
	$(MAKE) --no-print-directory -C backend test
	$(PNPM) --dir frontend test --pool=threads

migration-check: db-up
	$(MAKE) --no-print-directory -C backend migration-check
