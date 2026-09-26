# Phase 3 local acceptance runbook

Run repository commands in Ubuntu WSL2 from
`/home/btl4w/code/ai-native-work-management`. Keep `.venv`, `node_modules`
and provider credentials inside this environment. The local demo accounts are
`manager@example.test` and `nam.do@example.test`; the seed script supplies the
development password.

## Start and refresh the stack

```bash
make install
make db-up
make migrate
make seed
make containers-up
docker compose ps
```

`make containers-up` runs `docker compose up -d --build --wait` for PostgreSQL,
FastAPI, Next.js and the one AI worker. Run it again after frontend or backend
source changes to rebuild images. `make migrate` upgrades to the repository's
Alembic head and `make seed` adds the local demo organization, skills,
capacity and members. The seed is local only and is idempotent. The browser
acceptance command resets its separate `work_management_e2e` database, migrates
it and seeds it before starting Playwright:

```bash
make test-e2e
```

For source development, `make dev` starts the local API, frontend and worker.
When running a worker outside Compose, set `APP_WORKER_ORGANIZATION_IDS` to a
JSON array containing the seeded organization UUID. Find it with:

```bash
docker compose exec -T postgres psql -At -U work_management -d work_management \
  -c "SELECT id FROM organizations ORDER BY created_at, id LIMIT 1"
```

## Provider modes

`APP_AI_PROVIDER=mock` uses deterministic fixtures for local automated tests
and requires no hosted credential. `APP_AI_PROVIDER=disabled` leaves manual
People, Capacity, Team and Task assignment flows available. The hosted mode is
opt-in: set `APP_AI_PROVIDER=openai`, `APP_AI_MODEL` and
`APP_OPENAI_API_KEY` through the local shell or ignored secret store. Never put
the key, raw model context or hidden reasoning in a runbook, screenshot or Git.

## Manual demo

In Vietnamese, sign in as Manager, open **Con người & kỹ năng**, inspect a
member's verified skill evidence, set weekly capacity and leave, and inspect
the computed workload. Open a Project, create a Project Week and an unassigned
Task with a required skill and effort. In **Đội ngũ**, derive and confirm
requirements, inspect the ranking details, create a recommendation, edit it to
v2, inspect the read-only v1 diff and approve v2. Confirm the Team has members
while the Task remains unassigned. Open that Task and explicitly assign an
approved member. Sign in as Employee and confirm People and Team writes are
absent. Switch the language control to **en** and repeat the same path using
**People & skills**, **Capacity & workload** and the Project Team tab.

For Assistant, submit a Project-only request and verify there is no Team card.
Submit an explicit Project-plus-team request, approve the Project proposal,
then inspect the resumed Team step. A Manager must confirm requirements before
a recommendation can be approved. Team approval must leave every Task
unassigned. An exact Manager Task/person chat command uses the same audited
assignment service as the Task form; ambiguous names require clarification.

## Evidence and recovery

The Team card and `GET /api/v1/recommendations/{id}` expose immutable v1/v2
scores, the `ranking-v1` policy version, workload and evidence provenance.
Missing evidence contributes zero and cannot become a model fact. `make eval`
runs both bilingual redacted golden suites and prints only aggregate counts.
Inspect safe run status, tool versions, checkpoints and decision blocks through
the Assistant activity and tenant-scoped operational rows; never inspect or
export hidden reasoning or raw provider responses.

If an approval returns a stale version response, reload the latest
recommendation, review its diff and resubmit against its exact ETag. A failed
post-Project Team step leaves the approved Project intact and links to the
manual Team editor. With the provider disabled or explanation generation
failing, use the deterministic ranking and manual Team flow. Reuse the same
`Idempotency-Key` only when retrying the identical request; a changed payload
gets a new key. Verify the resulting Task and audit/outbox evidence before any
further retry.

## Gates

```bash
make lint
make typecheck
make test
make migration-check
make ai
make eval
make test-e2e
make containers-config-check
make ai-worker-check
make containers-up
docker compose ps
```

Live-provider checks are separate and credential-gated. Do not infer a phase
closure from a partial demo or from mocked evaluation alone.
