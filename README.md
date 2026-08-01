# End-to-End AI-Native Work Management Platform

The repository is being built one focused vertical step at a time. It currently
contains the Phase 1 frontend, FastAPI and database code foundations;
authentication and product data models are not implemented yet. Local Compose
currently runs PostgreSQL only.

## Local PostgreSQL

Prerequisite: Docker Desktop with WSL integration enabled for this distro.

Start PostgreSQL and wait until its health status is `healthy`:

```bash
cp .env.example .env
docker compose up -d postgres
docker compose ps
```

Verify the database and Alembic connection:

```bash
docker compose exec -T postgres \
  psql -U work_management -d work_management -c "select current_database(), current_user;"

cd backend
uv run alembic upgrade head
uv run alembic current --check-heads
```

Stop the container without deleting local database data:

```bash
docker compose down
```

The default credentials are local demonstration values only. Override them in
the ignored root `.env` file when needed. Do not use `docker compose down -v`
unless deleting the local database volume is intentional.

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
