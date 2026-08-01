# End-to-End AI-Native Work Management Platform

The repository is being built one focused vertical step at a time. It currently
contains the Phase 1 frontend, FastAPI and database code foundations;
the identity/organization schema, local demo accounts, session authentication,
login UI, tenant-scoped Project/Task APIs, and the bilingual Project, Task and
My Tasks workspace are available. The workspace includes actor-scoped caches,
server-confirmed mutations, structured errors, pagination and a persisted VI/EN
selector.
Local Compose currently runs PostgreSQL only; frontend and backend dev servers run
on the host.

## Accepted local environment

Run Codex and all repository commands inside Ubuntu WSL2 from the Linux-native
checkout:

```bash
cd ~/code/ai-native-work-management
```

Windows PowerShell is reserved for host-level backup or WSL management. Keeping
the repository on the WSL filesystem avoids the `/mnt/c` filesystem overhead for
Git, uv, pnpm, Next.js and test tooling.

Prerequisites in Ubuntu are GNU Make, Linux `uv`, Node.js 24 managed by `nvm`,
Corepack from that Node installation, and Docker Desktop with WSL integration
enabled for the Ubuntu distro. The verified Node runtime is `v24.18.1`.

In a fresh Ubuntu shell, activate the Linux Node runtime and Corepack before
running repository commands:

```bash
source ~/.nvm/nvm.sh
nvm install 24
nvm alias default 24
nvm use 24
corepack enable
command -v node
command -v corepack
node --version
node -p process.platform
```

The two executable paths must resolve to the active `nvm` Node 24 installation,
and `process.platform` must report `linux`.

Do not copy or reuse `backend/.venv` or `frontend/node_modules` from a Windows
checkout. Recreate both inside this Ubuntu checkout from the committed lockfiles.

The stable repository commands are:

```bash
make
make bootstrap
make lint
make typecheck
make test
make test-e2e
make migration-check
```

## One-command local development

From the repository root, run:

```bash
make
```

The default target installs locked dependencies, starts PostgreSQL, applies
migrations, idempotently seeds demo accounts, then runs FastAPI and Next.js in
parallel. Stop the foreground dev servers with `Ctrl+C`; stop PostgreSQL with:

```bash
make down
```

To prepare the database and return to the shell without starting dev servers:

```bash
make bootstrap
```

Demo accounts all use the local-only password `WorkDemo123!`:

| Persona | Email |
| --- | --- |
| Admin | `admin@example.test` |
| Manager | `manager@example.test` |
| Employee | `employee@example.test` |

## Local authentication API

After `make` has started the application, log in and store the HttpOnly session
cookie in a temporary cookie jar:

```bash
curl -i -c /tmp/work-management.cookies \
  -H 'Content-Type: application/json' \
  -d '{"email":"manager@example.test","password":"WorkDemo123!"}' \
  http://localhost:8000/api/v1/auth/login
```

Resolve the current authenticated actor, then revoke the session:

```bash
curl -b /tmp/work-management.cookies http://localhost:8000/api/v1/me
curl -i -X POST -b /tmp/work-management.cookies \
  http://localhost:8000/api/v1/auth/logout
```

The cookie contains an opaque random credential and an organization locator.
PostgreSQL stores only the token's SHA-256 hash. The organization value is not
trusted as authorization: the token must resolve to an active membership inside
the same RLS tenant context.

The browser-facing login page is `http://localhost:3000/login`. Browser API calls
use the same-origin `/api/v1` path, which Next.js proxies to FastAPI. Configure a
different backend origin with `API_ORIGIN` when necessary.

## Project API

With a Manager or Admin session in the cookie jar, create and inspect a Project:

```bash
curl -i -b /tmp/work-management.cookies \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: project-create-demo-001' \
  -d '{"name":"Customer onboarding","description":"Standardize onboarding"}' \
  http://localhost:8000/api/v1/projects

curl -b /tmp/work-management.cookies \
  http://localhost:8000/api/v1/projects
```

`POST /api/v1/projects` and `PATCH /api/v1/projects/{project_id}` require an
`Idempotency-Key` of 16–128 characters. Updates also require the current version
as `If-Match: "<version>"`; Project responses expose the matching `ETag`.
Manager/Admin can read all Projects in their tenant. Employees see only Projects
that contain a Task assigned to them.

## Task and member APIs

Manager/Admin can list assignable members, create an assigned Task and manage it
through the fixed Phase 1 workflow:

```bash
curl -b /tmp/work-management.cookies http://localhost:8000/api/v1/members

curl -i -b /tmp/work-management.cookies \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: task-create-demo-001' \
  -d '{"project_id":"<project-uuid>","title":"Collect documents","assignee_membership_id":"<membership-uuid>","due_date":"2026-08-12"}' \
  http://localhost:8000/api/v1/tasks
```

Task updates and status transitions require `If-Match` plus an idempotency key.
Employees use `/api/v1/my-tasks`, see only their assigned Tasks, and may perform
only the documented `TO_DO ↔ IN_PROGRESS ↔ DONE` edges on those Tasks.

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
RUN_POSTGRES_INTEGRATION=1 uv run pytest -m integration
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

Development uses Next.js with Webpack because Turbopack's first route compilation
can exceed the memory available to this WSL setup. On `/mnt/c`, the first compile
can still take tens of seconds due to Windows/WSL filesystem I/O; later requests
are cached. Keeping the repository on the WSL Linux filesystem gives a faster dev
loop.

Frontend quality checks:

```bash
cd frontend
corepack pnpm@10 lint
corepack pnpm@10 typecheck
corepack pnpm@10 test
corepack pnpm@10 build
```

Root commands include `make lint`, `make typecheck`, `make test` and
`make migration-check`.

For the browser acceptance test, install Playwright Chromium and its Ubuntu
runtime dependencies once:

```bash
cd frontend
corepack pnpm@10 exec playwright install chromium
sudo corepack pnpm@10 exec playwright install-deps chromium
```

Then run the production-build E2E flow from the repository root:

```bash
make test-e2e
```

The command recreates a dedicated `work_management_e2e` database, then uses
isolated ports `3100` and `8100` plus `.next-e2e`. It neither mutates the normal
local database nor stops/reuses a development server on ports `3000`/`8000`.

## Backend development

The backend currently provides the FastAPI application shell, configuration,
structured error handling, an async SQLAlchemy session factory, Alembic, the
Phase 1 identity/organization tables, local session authentication, member
lookup, and tenant-scoped Project/Task APIs. Product UI for these APIs is the
current Phase 1 workspace.

Prerequisite: install [uv](https://docs.astral.sh/uv/).

Run the backend:

```bash
cd backend
make up
```

Database commands from `backend/`:

```bash
make migrate
make seed
make migration-check
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
