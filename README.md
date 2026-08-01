# End-to-End AI-Native Work Management Platform

The repository is being built one focused vertical step at a time. It currently
contains the Phase 1 frontend, FastAPI and database code foundations;
authentication, product data models and Docker are not implemented yet.

## Frontend development

Prerequisites:

- Node.js 24 LTS
- Corepack

Run the frontend:

```bash
cd frontend
corepack pnpm@10 install --frozen-lockfile
corepack pnpm@10 dev
```

Frontend quality checks:

```bash
cd frontend
corepack pnpm@10 lint
corepack pnpm@10 typecheck
corepack pnpm@10 test
corepack pnpm@10 build
```

The root-level `make` commands documented in `PLAN.md` will be added in a later
tooling-focused step after the corresponding backend and local infrastructure
exist.

## Backend development

The backend foundation currently provides the FastAPI application shell,
configuration, structured error handling, an async SQLAlchemy session factory
and Alembic configuration. It does not define product tables or endpoints yet.

Prerequisite: install [uv](https://docs.astral.sh/uv/).

Run the backend:

```bash
cd backend
uv sync --locked
uv run fastapi dev app/main.py
```

FastAPI runs at `http://localhost:8000`; its development API documentation is at
`http://localhost:8000/docs`.

Backend quality checks:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv run alembic heads
```
