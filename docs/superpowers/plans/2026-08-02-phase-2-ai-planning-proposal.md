# Phase 2 AI Planning Proposal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking. This repository requires explicit user authorization before any
> commit, push or remote operation.

**Goal:** Deliver the complete Phase 2 vertical slice: manual project planning,
an asynchronous bounded-agentic planning workflow, an editable/versioned AI
proposal and a Manager-only approval transaction that creates business records
exactly once.

**Architecture:** Extend the FastAPI modular monolith with planning domain and
application services, tenant-qualified PostgreSQL persistence, one database-backed
worker and a separate top-level `ai/` Python package. LangGraph coordinates the
typed planning workflow; LangChain/OpenAI live behind a project-owned Model
Gateway; LangSmith is an optional non-blocking trace/evaluation adapter. The
Next.js UI uses REST snapshots plus SSE progress and retains a provider-independent
manual flow.

**Tech Stack:** Python 3.13, FastAPI 0.140.3, Pydantic 2, SQLAlchemy 2 async,
psycopg 3, Alembic, PostgreSQL 18, LangGraph `>=1.2,<1.3`, LangChain
`>=1.3,<1.4`, langchain-openai `>=1.4,<1.5`, LangSmith `>=0.10,<0.11`, Next.js
16, React 19, TypeScript strict, TanStack Query 5, Zod 4, next-intl 4, Vitest,
Testing Library and Playwright.

> **Correction checkpoint — 2026-08-09:** Tasks 1–8 remain the implementation
> history and Task 8 approval semantics remain authoritative. Task 9 below is
> superseded because it treated one Planning Run as the Assistant conversation
> and produced a planning dashboard instead of a conversation-first chat app.
> Do not execute or close Task 9–11 from this document. Use the approved
> conversation-first design at
> `docs/superpowers/specs/2026-08-09-conversation-first-ai-assistant-design.md`
> and its replacement implementation plan after that written spec is reviewed.
> Task 10 and Task 11 remain blocked until the
> corrective Assistant slice passes its own checkpoint.

## Global constraints

- Follow `AGENTS.md`, `PLAN.md` Phase 2,
  `docs/phase-2/UX_SPEC.md` and
  `docs/phase-2/TECHNICAL_FOUNDATION.md` in that precedence.
- Work only inside Ubuntu WSL2 at
  `/home/btl4w/code/ai-native-work-management`.
- Preserve the existing user changes in `.gitignore`, `README.md` and
  `docs/THIET_KE_FLOW_APP.md`.
- Do not commit, push or create a PR unless the user explicitly authorizes it.
- Complete Tasks 1 and 2 together before starting the AI slice; they form the
  provider-independent manual planning vertical slice.
- All product APIs stay under `/api/v1` and use the existing structured error
  contract.
- Every retryable mutation requires `Idempotency-Key`; updates/deletes require
  `If-Match` and return an updated `ETag`.
- Every tenant-owned row, index, unique constraint, foreign key, job/event
  payload and cache/query key includes tenant context.
- Enable and force PostgreSQL RLS; API and worker roles never use `BYPASSRLS`.
- AI output is a proposal until Manager approval. AI cannot approve, assign,
  write PostgreSQL directly or bypass deterministic validation.
- Do not persist hidden chain-of-thought. Raw AI context expires within 30 days;
  redacted traces expire within 90 days.
- Default tests use the deterministic mock provider. Live OpenAI tests are
  opt-in, credential-gated and excluded from `make test`.
- All user-facing text uses Vietnamese/English translation keys.
- Do not add Redis, Celery, a message broker, Qdrant/RAG/GraphRAG, Calendar,
  microservices, multi-agent swarms, deployment automation, self-hosted models,
  fine-tuning, distillation or MLflow.
- At each task checkpoint run the task-specific tests plus `make lint` and
  `make typecheck`; do not claim the task complete from a happy path alone.

---

## Planned file map

### Manual planning backend

- `backend/app/modules/work/planning/domain/` — framework-independent Goal,
  Milestone, Dependency and Acceptance Criterion values/invariants.
- `backend/app/modules/work/planning/application/manual_ports.py` — repository
  and transaction protocols.
- `backend/app/modules/work/planning/application/manual_service.py` — Manager
  authorization, request fingerprinting and manual transaction boundaries.
- `backend/app/modules/work/planning/adapters/database_models.py` — SQLAlchemy
  tenant-owned planning models.
- `backend/app/modules/work/planning/adapters/manual_repository.py` — RLS-aware
  CRUD, idempotency and audit implementation.
- `backend/app/modules/work/planning/api/` — typed REST schemas, routes and
  composition-root dependency.
- `backend/alembic/versions/0005_planning_core.py` — planning tables, Task
  `milestone_id`, tenant-qualified constraints, grants and forced RLS.

### AI package and runtime

- `ai/pyproject.toml` and `ai/src/work_management_ai/` — independent Python
  distribution containing Model Gateway, prompts, schemas, graph, verifier,
  tracing and evaluation.
- `backend/app/modules/planning_runs/` — workflow/proposal/approval business
  persistence and application services.
- `backend/alembic/versions/0006_ai_planning_runs.py` — proposal, approval,
  workflow, model/context, job/event and outbox persistence.
- `backend/app/worker.py` — one-process job/outbox loop using shared application
  composition.

### Frontend

- `frontend/src/features/planning/` — manual Project Plan UI and typed REST
  client.
- `frontend/src/features/ai-proposals/` — chat, wizard cards, proposal editor,
  validation/diff, SSE and approval UI.
- `frontend/src/features/work/workspace.tsx` — shell/navigation integration only;
  new feature behavior stays in focused files.

---

### Task 1: Manual planning backend and PostgreSQL isolation

**Deliverable:** Manager/Admin can CRUD Goal, Milestone, Dependency and
Acceptance Criterion through audited/versioned APIs; Employee writes and all
cross-tenant references are rejected. No AI dependency is installed.

**Files:**

- Create: `backend/app/modules/work/planning/__init__.py`
- Create: `backend/app/modules/work/planning/domain/goals.py`
- Create: `backend/app/modules/work/planning/domain/milestones.py`
- Create: `backend/app/modules/work/planning/domain/dependencies.py`
- Create: `backend/app/modules/work/planning/domain/acceptance_criteria.py`
- Create: `backend/app/modules/work/planning/application/manual_ports.py`
- Create: `backend/app/modules/work/planning/application/manual_service.py`
- Create: `backend/app/modules/work/planning/adapters/database_models.py`
- Create: `backend/app/modules/work/planning/adapters/manual_repository.py`
- Create: `backend/app/modules/work/planning/api/schemas.py`
- Create: `backend/app/modules/work/planning/api/routes.py`
- Create: `backend/app/modules/work/planning/api/dependencies.py`
- Create: `backend/alembic/versions/0005_planning_core.py`
- Modify: `backend/alembic/env.py`
- Modify: `backend/app/modules/work/adapters/database_models.py`
- Modify: `backend/app/modules/work/adapters/task_repository.py`
- Modify: `backend/app/modules/work/domain/tasks.py`
- Modify: `backend/app/modules/work/application/task_ports.py`
- Modify: `backend/app/modules/work/application/task_service.py`
- Modify: `backend/app/modules/work/api/task_schemas.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_planning_domain.py`
- Test: `backend/tests/test_planning_service.py`
- Test: `backend/tests/test_planning_api_integration.py`
- Test: `backend/tests/test_planning_schema_integration.py`
- Modify test: `backend/tests/test_task_domain.py`
- Modify test: `backend/tests/test_task_api_integration.py`

**Interfaces:**

- Consumes: `AuthenticatedActor`, `Project`, `Task`, `AuditEventModel` and the
  established idempotency/ETag/error conventions.
- Produces: `Goal`, `Milestone`, `TaskDependency`, `AcceptanceCriterion`,
  `ManualPlanningService`, `ManualPlanningTransactionFactory` and CRUD routers
  used by Tasks 2 and 8.

- [ ] **Step 1: Write domain tests for normalization and invariants**

```python
def test_dependency_rejects_self_edge() -> None:
    task_id = uuid4()
    with pytest.raises(InvalidDependencyError):
        TaskDependencyDraft.create(predecessor_task_id=task_id, successor_task_id=task_id)


def test_acceptance_criterion_normalizes_required_text() -> None:
    draft = AcceptanceCriterionDraft.create(task_id=uuid4(), text="  Customs form accepted  ")
    assert draft.text == "Customs form accepted"
```

Run:

```bash
cd backend && uv run pytest tests/test_planning_domain.py -q
```

Expected: FAIL because the planning domain modules do not exist.

- [ ] **Step 2: Implement immutable domain values and errors**

Use dataclasses with the established Phase 1 pattern. The public drafts/entities
must expose these exact fields:

```python
@dataclass(frozen=True, slots=True)
class GoalDraft:
    project_id: UUID
    title: str
    description: str | None
    expected_outcomes: tuple[str, ...]
    target_date: date | None


@dataclass(frozen=True, slots=True)
class MilestoneDraft:
    project_id: UUID
    name: str
    description: str | None
    target_date: date | None
    position: int


@dataclass(frozen=True, slots=True)
class TaskDependencyDraft:
    predecessor_task_id: UUID
    successor_task_id: UUID


@dataclass(frozen=True, slots=True)
class AcceptanceCriterionDraft:
    task_id: UUID
    text: str
    position: int
```

Use explicit `Patch` types with supplied flags for nullable fields. Entity types
include `id`, `organization_id`, `version`, `created_at` and `updated_at`.

Run the domain test and expect PASS.

- [ ] **Step 3: Write service tests for authorization, cycle/date validation and audit rejection**

```python
@pytest.mark.asyncio
async def test_employee_goal_write_is_rejected_and_audited() -> None:
    transaction = FakeManualPlanningTransaction()
    service = ManualPlanningService(lambda: transaction)
    with pytest.raises(PlanningForbiddenError):
        await service.create_goal(
            actor=actor(MembershipRole.EMPLOYEE),
            project_id=uuid4(),
            title="Forbidden",
            description=None,
            expected_outcomes=(),
            target_date=None,
            request_id="req-1",
            idempotency_key="goal-create-key-1",
        )
    assert transaction.rejections == ["goal.created:FORBIDDEN"]
```

Add concrete cases for one-Goal-per-Project, Task/Milestone same Project,
cross-Project dependency, duplicate edge, cycle `A → B → C → A`, Task due after
Milestone target date, duplicate normalized criterion and stale `If-Match`.

Run the service test and expect FAIL because service/ports are absent.

- [ ] **Step 4: Implement the transaction port and manual application service**

`ManualPlanningRepository` must define typed list/get/create/update/delete
methods for each resource plus:

```python
async def validate_dependency_edge(
    self,
    *,
    actor: AuthenticatedActor,
    predecessor_task_id: UUID,
    successor_task_id: UUID,
) -> None: ...

async def audit_rejection(
    self,
    *,
    actor: AuthenticatedActor,
    action: str,
    request_id: str,
    reason_code: str,
    idempotency_key: str | None = None,
    resource_id: UUID | None = None,
) -> None: ...
```

`ManualPlanningService` authorizes only `ADMIN` and `MANAGER` for mutations,
normalizes/fingerprints requests and owns each transaction. Read methods allow an
Employee only when existing Project/Task visibility allows the referenced data.

Run:

```bash
cd backend && uv run pytest tests/test_planning_domain.py tests/test_planning_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Write migration/RLS tests before the migration**

Assert exact table presence, forced RLS, grants and cross-tenant denial for:

```python
PLANNING_TABLES = {
    "goals",
    "milestones",
    "task_dependencies",
    "acceptance_criteria",
}
```

Also assert `tasks.milestone_id` exists and the composite foreign key
`(organization_id, milestone_id)` prevents a Task from referencing another
tenant's Milestone.

Run:

```bash
make migration-check
```

Expected: FAIL because revision `0005` and tables do not exist.

- [ ] **Step 6: Implement SQLAlchemy models and Alembic revision `0005`**

The migration must:

- Create all four tables with tenant-qualified unique/FK constraints.
- Add nullable `tasks.milestone_id`, index it with `organization_id` and add the
  composite Milestone FK.
- Enforce one Goal using `UNIQUE (organization_id, project_id)`.
- Enforce unique dependency edges and `predecessor_task_id <> successor_task_id`.
- Enforce positive display positions.
- Add the task/date and cycle checks in the application transaction; PostgreSQL
  constraints enforce only invariants expressible without unsafe triggers.
- Enable and force RLS on every new table.
- Create tenant policies using `current_setting('app.organization_id', true)`.
- Grant the minimum CRUD privileges to `app_runtime`.
- Provide a complete downgrade in reverse dependency order.

Import the planning models in `backend/alembic/env.py` so `alembic check` sees no
drift.

- [ ] **Step 7: Write failing API integration tests**

Exercise all required API families:

```text
/api/v1/goals
/api/v1/milestones
/api/v1/task-dependencies
/api/v1/acceptance-criteria
```

For each family assert Manager create/read/update/delete, idempotent replay,
stale `If-Match`, Employee mutation `403`, inaccessible foreign resource `404`,
cross-tenant reference rejection and successful/rejected audit rows.

Run the test and expect FAIL because routers/repositories are absent.

- [ ] **Step 8: Implement persistence, schemas, routes and composition**

Follow the Phase 1 response pattern: mutations return `ETag`, replay returns
`Idempotency-Replayed: true`, missing `If-Match` returns 428 and domain errors map
to the shared `ErrorResponse`. Add `DELETE` to CORS methods.

Task responses gain:

```python
milestone_id: UUID | None
```

Task create/update requests gain the same optional field. `TaskDraft` and
`TaskPatch` validate it through the Task repository, which confirms same tenant,
same Project and the Task/Milestone date invariant. Updating a Milestone target
date performs the inverse check against every linked Task before commit.

Register `manual_planning_service` and the router in `create_app` without
changing existing injectable service behavior in tests.

- [ ] **Step 9: Verify the complete backend slice and stop for review**

```bash
make migration-check
cd backend && uv run pytest -m "not integration" -q
cd .. && make lint && make typecheck
```

Expected: all commands PASS. Report migration revision, tests run and changed
files. Do not start Task 2 until the user accepts this checkpoint.

---

### Task 2: Manual Project Plan frontend

**Deliverable:** Manager/Admin can manage the Project Goal, Milestones,
Dependencies and Acceptance Criteria without AI; Employees have the approved
read-only view.

**Files:**

- Create: `frontend/src/features/planning/contracts.ts`
- Create: `frontend/src/features/planning/api.ts`
- Create: `frontend/src/features/planning/project-plan.tsx`
- Create: `frontend/src/features/planning/project-plan.test.tsx`
- Create: `frontend/src/features/planning/contracts.test.ts`
- Create: `frontend/src/features/planning/api.test.ts`
- Modify: `frontend/src/features/work/contracts.ts`
- Modify: `frontend/src/features/work/workspace.tsx`
- Modify: `frontend/src/features/work/workspace.test.tsx`
- Modify: `frontend/src/features/work/openapi-contract.json`
- Modify: `frontend/src/shared/i18n/messages/en.json`
- Modify: `frontend/src/shared/i18n/messages/vi.json`
- Modify: `backend/tests/test_frontend_openapi_contract.py`

**Interfaces:**

- Consumes: Task 1 REST contracts and resource versions.
- Produces: `ProjectPlan`, `Goal`, `Milestone`, `TaskDependency` and
  `AcceptanceCriterion` Zod types plus `ProjectPlanPanel` for later approved-plan
  E2E verification.

- [ ] **Step 1: Write Zod contract tests**

```typescript
it("parses a project plan response", () => {
  expect(projectPlanSchema.parse({
    goal: null,
    milestones: [],
    dependencies: [],
    acceptance_criteria: [],
  })).toEqual({ goal: null, milestones: [], dependencies: [], acceptance_criteria: [] });
});
```

Add invalid UUID, empty criterion and missing-version cases. Run:

```bash
corepack pnpm@10 --dir frontend test src/features/planning/contracts.test.ts
```

Expected: FAIL because the contracts do not exist.

- [ ] **Step 2: Implement planning contracts and REST functions**

Expose:

```typescript
export function getProjectPlan(projectId: string): Promise<ProjectPlan>;
export function createGoal(input: GoalInput, key: string): Promise<ApiResult<Goal>>;
export function updateGoal(id: string, input: GoalPatch, version: number, key: string): Promise<ApiResult<Goal>>;
export function deleteGoal(id: string, version: number, key: string): Promise<void>;
```

Repeat explicit functions for Milestone, Dependency and Acceptance Criterion.
All mutations set the exact idempotency/version headers used by Phase 1.

Run contract/API tests and expect PASS.

- [ ] **Step 3: Write component tests for manual and read-only flows**

Cover these visible states:

```text
Manager: Project detail → Plan → empty CTA → create Goal/Milestone
Manager: Task detail → Acceptance Criteria → add/edit/delete
Manager: Dependency editor → cycle error summary
Employee: permitted Project Plan → read-only, no mutation CTA
Provider unavailable: all manual controls remain enabled
```

Assert keyboard dialog focus, error-summary focus, stale reload action and
Vietnamese/English keys.

- [ ] **Step 4: Implement focused `ProjectPlanPanel`**

Keep `workspace.tsx` responsible only for shell/navigation/selection. The panel
owns its TanStack Query keys:

```typescript
const planKey = ["planning", organizationId, actorMembershipId, projectId] as const;
```

Use the existing mutation-attempt semantics so a network retry reuses its key
until a definitive 4xx response. Render Project Goal as a section, never a
top-level Goals navigation tab.

- [ ] **Step 5: Update OpenAPI manifest and bilingual copy**

Add all new enum/schema shapes to `openapi-contract.json` and assert them in the
backend contract test. Add translation keys under `planning` and change the shell
phase badge from Phase 1 to Phase 2 wording without hard-coded component strings.

- [ ] **Step 6: Verify the manual vertical slice and stop for review**

```bash
corepack pnpm@10 --dir frontend test --pool=threads
make lint
make typecheck
make migration-check
```

Expected: PASS. Demonstrate manual planning with the AI provider unset. Do not
start Task 3 until this provider-independent slice is accepted.

---

### Task 3: Separate AI package, configuration and Model Gateway

**Deliverable:** The repository has a separately testable `ai/` package with a
provider-neutral structured-output gateway, deterministic mock provider and an
OpenAI adapter that is never required by the default tests.

**Files:**

- Create: `ai/pyproject.toml`
- Create: `ai/src/work_management_ai/__init__.py`
- Create: `ai/src/work_management_ai/model_gateway/contracts.py`
- Create: `ai/src/work_management_ai/model_gateway/errors.py`
- Create: `ai/src/work_management_ai/model_gateway/mock.py`
- Create: `ai/src/work_management_ai/model_gateway/openai.py`
- Create: `ai/src/work_management_ai/schemas/planning.py`
- Create: `ai/tests/test_model_gateway_contract.py`
- Create: `ai/tests/test_openai_adapter.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `backend/Makefile`

**Interfaces:**

- Consumes: no backend imports; provider credentials arrive through typed
  constructor/config values.
- Produces: `ModelGateway`, `StructuredModelRequest[T]`,
  `StructuredModelResponse[T]`, `MockModelGateway`, `OpenAIModelGateway` and
  `PlanningModelOutput`.

- [ ] **Step 1: Write the gateway contract tests**

```python
@pytest.mark.asyncio
async def test_mock_gateway_returns_typed_output_and_version_metadata() -> None:
    gateway = MockModelGateway(fixtures={"planning.default.vi.v1": VALID_PLAN})
    response = await gateway.generate_structured(
        StructuredModelRequest(
            invocation_key="planning.default.vi.v1",
            messages=(ModelMessage(role="user", content="Lập kế hoạch xuất nhập khẩu"),),
            output_schema=PlanningModelOutput,
            timeout_seconds=60,
        )
    )
    assert isinstance(response.parsed, PlanningModelOutput)
    assert response.model_ref == "mock:planning-v1"
```

Also test normalized timeout, unavailable, rate-limit and invalid-output errors.
Run with:

```bash
cd backend && uv run pytest ../ai/tests/test_model_gateway_contract.py -q
```

Expected: FAIL because the separately installed AI package does not exist.

- [ ] **Step 2: Create the package and lock dependency ranges**

`ai/pyproject.toml` uses a `src/` layout and Python `>=3.13,<3.14`. Add direct
dependencies:

```toml
dependencies = [
  "langchain>=1.3,<1.4",
  "langchain-openai>=1.4,<1.5",
  "langgraph>=1.2,<1.3",
  "langsmith>=0.10,<0.11",
  "pydantic>=2,<3",
]
```

Add `work-management-ai` to `backend/pyproject.toml` with an editable uv source
at `../ai`, then run:

```bash
cd backend && uv lock && uv sync --locked
```

Review the resolved lock diff before continuing; do not accept a Python version
or major-version downgrade.

- [ ] **Step 3: Implement project-owned gateway types and mock adapter**

Use Pydantic output schemas and project dataclasses/Protocols. Do not expose
`BaseMessage`, `ChatOpenAI` or provider response types from the contract module.
The mock adapter chooses fixtures deterministically by `invocation_key`.

Define the model-facing plan shape explicitly:

```python
class PlanningModelOutput(BaseModel):
    project: ProposedProject
    goal: ProposedGoal
    milestones: list[ProposedMilestone]
    tasks: list[ProposedTask]
    dependencies: list[ProposedDependency]
    assumptions: list[ProposedAssumption]


class ProposedTask(BaseModel):
    ref: str
    milestone_ref: str | None
    title: str
    description: str | None
    due_date: date | None
    acceptance_criteria: list[str]
```

`ProposedTask` intentionally has no AI-produced assignee field. The backend
proposal editor adds `assignee_membership_id: UUID | None` as Manager-authored
provenance before approval.

Run the contract tests and expect PASS.

- [ ] **Step 4: Test and implement the OpenAI adapter without a live call**

Patch/inject the LangChain chat model and assert that the adapter uses typed
structured output, configured model name, 60-second timeout and normalized
errors. Mark any credential-using test `live_provider` and exclude it by default.

- [ ] **Step 5: Add validated runtime configuration**

Add settings with these behaviors:

```python
ai_provider: Literal["disabled", "mock", "openai"] = "disabled"
ai_model: str = ""
openai_api_key: SecretStr | None = None
langsmith_tracing: bool = False
langsmith_api_key: SecretStr | None = None
ai_raw_context_retention_days: int = Field(default=30, ge=0, le=30)
ai_redacted_trace_retention_days: int = Field(default=90, ge=0, le=90)
```

Production `openai` configuration requires both a non-empty model and key.
Local/test defaults remain `disabled` unless the deterministic mock is selected.
Never print secrets in settings errors.

- [ ] **Step 6: Add package commands and verify**

Add backend/root commands that include `ai/src` and `ai/tests` in Ruff, Pyright
and Pytest. Reserve `make eval` for Task 10's executable evaluation suite.

```bash
make lint
make typecheck
make test
```

Expected: PASS without network or AI credentials. Stop for review.

---

### Task 3A: Local package and container boundaries

**Deliverable:** The polyglot monorepo gives frontend, backend API and AI clean,
independent development/build boundaries without turning AI into an HTTP
microservice or starting the Task 5 worker early.

**Approved architecture adjustment:**

- `backend/.venv` and `ai/.venv` are separate local environments.
- `ai/uv.lock` proves the AI package independently; `backend/uv.lock` remains
  the integrated API/worker runtime lock and installs `ai/` as a local package.
- `frontend`, `backend-api` and `ai-check` are independently built images.
- `ai-check` is an opt-in, short-lived quality container with no port, database
  dependency or daemon. Task 5 replaces this temporary runtime role with the
  real PostgreSQL-backed `ai-worker`; it does not add an AI network API.
- Root Compose remains local tooling, not Post-MVP deployment automation.

**Files and commands:** See
`docs/superpowers/plans/2026-08-03-local-container-boundaries.md` for the
bounded implementation checklist and verification evidence. Stop for review
after this adjustment; do not start Task 4 without explicit authorization.

---

### Task 4: Workflow, proposal and approval persistence

**Deliverable:** PostgreSQL stores tenant-isolated runs, typed checkpoints,
immutable proposal versions, approvals, jobs, progress events, model/context
metadata and transactional outbox rows.

**Files:**

- Create: `backend/app/modules/planning_runs/domain/models.py`
- Create: `backend/app/modules/planning_runs/application/ports.py`
- Create: `backend/app/modules/planning_runs/adapters/database_models.py`
- Create: `backend/app/modules/planning_runs/adapters/repository.py`
- Create: `backend/alembic/versions/0006_ai_planning_runs.py`
- Modify: `backend/alembic/env.py`
- Test: `backend/tests/test_planning_run_domain.py`
- Test: `backend/tests/test_ai_planning_schema_integration.py`
- Test: `backend/tests/test_workflow_repository_integration.py`

**Interfaces:**

- Consumes: authenticated tenant IDs, existing audit tables and Task 1 business
  references.
- Produces: `WorkflowRun`, `WorkflowCheckpoint`, `Proposal`, `ProposalVersion`,
  `Approval`, `WorkflowJob`, `WorkflowEvent`, `OutboxEvent` and
  `PlanningRunTransactionFactory`.

- [ ] **Step 1: Write lifecycle transition tests**

```python
def test_ready_proposal_edit_supersedes_approval() -> None:
    proposal = ready_proposal(version=4, approval_id=uuid4())
    edited = proposal.edit(next_version=5, edited_by=uuid4())
    assert edited.status is ProposalStatus.DRAFT
    assert edited.superseded_approval_id == proposal.approval_id
```

Add invalid run/proposal/approval transition and terminal read-only tests.

- [ ] **Step 2: Implement domain enums and transitions**

Use exact states from the Technical Foundation. Keep Run, Proposal and Approval
state machines separate. `ProposalVersion` content is immutable JSON-compatible
structured data with provenance; it is not a business entity until approval.

- [ ] **Step 3: Write migration tests for all persistence tables**

Assert forced RLS and minimum grants for:

```python
AI_TABLES = {
    "proposals", "proposal_versions", "approvals",
    "workflow_runs", "workflow_checkpoints", "workflow_jobs", "workflow_events",
    "model_invocations", "context_references", "outbox_events",
}
```

Assert unique `(organization_id, workflow_run_id, sequence)`, one current
proposal version, approval-to-version tenant FKs, outbox `event_id` uniqueness and
job lease indexes.

- [ ] **Step 4: Implement migration and SQLAlchemy models**

Use JSONB only for typed proposal/checkpoint/event/envelope payloads. Put queryable
identity, lifecycle, version, lease and retention fields in columns. Add Alembic
RLS policies/grants and import models in `env.py`.

- [ ] **Step 5: Write and implement repository tests**

Cover atomic run+job creation, immutable version insert, approval superseding,
event sequencing, claim with `FOR UPDATE SKIP LOCKED`, lease expiry/reclaim,
bounded attempt increments, checkpoint upsert and outbox claim/publish.

The repository API must include:

```python
async def claim_job(self, *, worker_id: str, now: datetime, lease_until: datetime) -> WorkflowJob | None: ...
async def append_event(self, *, run_id: UUID, event_type: str, public_payload: dict[str, object]) -> WorkflowEvent: ...
async def save_checkpoint(self, *, run_id: UUID, node: str, state: dict[str, object]) -> WorkflowCheckpoint: ...
```

- [ ] **Step 6: Verify persistence and stop for review**

```bash
make migration-check
cd backend && uv run pytest tests/test_planning_run_domain.py tests/test_workflow_repository_integration.py -q
cd .. && make lint && make typecheck
```

Expected: PASS with cross-tenant direct-SQL attempts denied.

---

### Task 5: PostgreSQL worker, lease recovery and outbox dispatcher

**Deliverable:** A separate worker process executes queued workflow commands and
dispatches outbox records safely without Redis or a broker.

**Files:**

- Create: `backend/app/modules/planning_runs/application/job_service.py`
- Create: `backend/app/modules/planning_runs/application/outbox_service.py`
- Create: `backend/app/worker.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/Makefile`
- Modify: `Makefile`
- Test: `backend/tests/test_job_service.py`
- Test: `backend/tests/test_worker_integration.py`

**Interfaces:**

- Consumes: Task 4 job/checkpoint/outbox ports.
- Produces: `JobService.run_once(worker_id: str) -> bool`,
  `OutboxService.dispatch_once(worker_id: str) -> bool` and the stable command
  `make worker-dev`.

- [ ] **Step 1: Write lease/retry service tests**

```python
@pytest.mark.asyncio
async def test_failed_job_is_requeued_with_bounded_backoff() -> None:
    repository = FakeJobRepository(job=queued_job(max_attempts=3))
    service = JobService(repository, handlers={"planning.start": failing_handler})
    assert await service.run_once(worker_id="worker-test") is True
    assert repository.job.status is JobStatus.QUEUED
    assert repository.job.attempt_count == 1
    assert repository.job.available_at > repository.now
```

Add terminal failure, expired lease reclaim, unknown job type and idempotent
outbox replay tests.

- [ ] **Step 2: Implement one-iteration services**

The service, not the CLI loop, owns claim/dispatch decisions. Handler input is a
typed `WorkflowJob`; each handler re-establishes organization context inside its
transaction. Use capped exponential backoff and persisted safe error codes.

- [ ] **Step 3: Implement the worker loop and shutdown behavior**

`python -m app.worker` creates the shared database engine, Model Gateway and
handler registry, loops over `run_once`, waits briefly only when no work exists,
and exits cleanly on SIGINT/SIGTERM. It never starts FastAPI or a network AI
service.

- [ ] **Step 4: Add worker settings and commands**

```python
worker_poll_interval_seconds: float = Field(default=0.5, ge=0.1, le=10)
worker_lease_seconds: int = Field(default=60, ge=10, le=600)
worker_max_job_attempts: int = Field(default=3, ge=1, le=5)
```

Root `make dev` starts API, worker and frontend with `-j3`. Add a separate
`worker-dev` command for focused debugging.

- [ ] **Step 5: Verify crash recovery and stop for review**

```bash
cd backend && uv run pytest tests/test_job_service.py tests/test_worker_integration.py -q
cd .. && make lint && make typecheck
```

Expected: PASS and no live model/network call.

---

### Task 6: Bounded-agentic LangGraph planning workflow

**Deliverable:** The mock-backed planning graph can understand a request, pause
for missing information, produce typed output, repair once, verify, persist a
proposal and pause at Manager decision.

**Files:**

- Create: `ai/src/work_management_ai/prompts/planning.py`
- Create: `ai/src/work_management_ai/workflows/planning/state.py`
- Create: `ai/src/work_management_ai/workflows/planning/context.py`
- Create: `ai/src/work_management_ai/workflows/planning/policy.py`
- Create: `ai/src/work_management_ai/workflows/planning/verifier.py`
- Create: `ai/src/work_management_ai/workflows/planning/graph.py`
- Create: `ai/src/work_management_ai/workflows/planning/ports.py`
- Create: `ai/src/work_management_ai/tracing.py`
- Create: `ai/tests/test_planning_verifier.py`
- Create: `ai/tests/test_planning_graph.py`
- Create: `ai/tests/fixtures/planning_vi.json`
- Create: `ai/tests/fixtures/planning_en.json`

**Interfaces:**

- Consumes: Task 3 `ModelGateway`; injected `PlanningContextPort`,
  `PlanningPersistencePort` and `TracePort` implementations.
- Produces: `PlanningState`, `PlanningGraph`, `PlanningValidationResult` and job
  handlers used by Task 7.

- [ ] **Step 1: Write verifier tests**

```python
def test_verifier_blocks_cycle_and_unassigned_task() -> None:
    result = verify_plan(plan_with_cycle_and_missing_assignee())
    assert {(item.path, item.code) for item in result.errors} == {
        ("tasks[t1].assignee_membership_id", "ASSIGNEE_REQUIRED"),
        ("dependencies", "DEPENDENCY_CYCLE"),
    }
    assert result.can_approve is False
```

Cover one Goal, temporary-reference resolution, same-project links, dates,
duplicate Criteria, maximum proposal sizes and warning/non-blocking behavior.

- [ ] **Step 2: Implement the deterministic verifier**

The verifier accepts only `PlanningModelOutput` plus permitted context facts. It
does not invoke a model. Return ordered field paths, stable codes, translation
keys, severity and `can_approve`.

- [ ] **Step 3: Write graph branch/pause/resume tests**

Test exact paths:

```text
planning request → missing info interrupt → Manager answer → proposal interrupt
valid request → proposal interrupt
malformed output → repair → proposal
malformed twice → manual fallback
verifier rejection → one revision → draft errors
unsupported capability → terminal safe response
```

Assert a stable `thread_id == str(run_id)`, persisted state contains no chain of
thought and node side effects remain idempotent when a resumed interrupt restarts
the node.

- [ ] **Step 4: Implement graph state, nodes and conditional edges**

`PlanningState` contains only fields approved in the Technical Foundation. The
graph nodes are:

```python
NODES = (
    "policy_and_scope_guard",
    "load_permitted_context",
    "planning_agent",
    "generate_structured_plan",
    "validate_schema",
    "deterministic_verifier",
    "persist_proposal",
    "await_manager_input",
    "await_manager_decision",
    "manual_fallback",
)
```

Use dynamic LangGraph interrupts for human checkpoints. The graph cannot invoke
an approval/business-write tool.

- [ ] **Step 5: Add versioned bilingual prompts and tracing adapter**

Prompts export stable constants such as `PLANNING_PROMPT_VERSION = "1.0.0"` and
separate instruction/context/untrusted-input sections. `TracePort` receives only
redacted metadata; `NoopTracePort` is default and LangSmith failure is swallowed
after safe logging.

- [ ] **Step 6: Verify graph behavior and stop for review**

```bash
cd backend && uv run pytest ../ai/tests/test_planning_verifier.py ../ai/tests/test_planning_graph.py -q
cd .. && make lint && make typecheck
```

Expected: PASS deterministically with Vietnamese and English fixtures.

---

### Task 7: Planning-run, proposal-edit and SSE APIs

**Deliverable:** Manager/Admin can create/resume planning runs, load recent runs,
edit immutable proposal versions and receive replayable workflow progress. An
Employee cannot enumerate or mutate AI runs.

**Files:**

- Create: `backend/app/modules/planning_runs/application/run_service.py`
- Create: `backend/app/modules/planning_runs/application/proposal_service.py`
- Create: `backend/app/modules/planning_runs/api/schemas.py`
- Create: `backend/app/modules/planning_runs/api/routes.py`
- Create: `backend/app/modules/planning_runs/api/dependencies.py`
- Create: `backend/app/modules/planning_runs/adapters/ai_runtime.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_planning_run_service.py`
- Test: `backend/tests/test_planning_run_api_integration.py`
- Test: `backend/tests/test_workflow_sse.py`

**Interfaces:**

- Consumes: Tasks 4–6 persistence, job service and graph runtime.
- Produces: required planning/workflow/proposal endpoints and public SSE event
  contract used by Task 9.

- [ ] **Step 1: Write run-service tests**

Assert Manager/Admin create run+job+audit atomically, Employee rejection is
audited, unsupported capability is explicit, posting a message only resumes a
matching `NEEDS_INPUT` checkpoint and proposal edit v4 creates DRAFT v5 while
superseding the v4 approval.

- [ ] **Step 2: Implement run/proposal services and the AI adapter boundary**

Expose:

```python
async def create_planning_run(
    *, actor: AuthenticatedActor, message: str, locale: Literal["vi", "en"],
    request_id: str, idempotency_key: str,
) -> WorkflowRunMutationResult: ...

async def edit_proposal(
    *, actor: AuthenticatedActor, proposal_id: UUID,
    expected_version: int, content: dict[str, object],
    request_id: str, idempotency_key: str,
) -> ProposalMutationResult: ...
```

The backend adapter maps persisted backend proposal JSON to/from the separate AI
Pydantic schema. Backend domain/application modules do not import LangGraph or
LangChain.

- [ ] **Step 3: Write API and error-contract tests**

Cover:

```text
POST /api/v1/ai/planning-runs                  → 202 + Location
GET  /api/v1/workflow-runs                     → recent tenant runs
GET  /api/v1/workflow-runs/{run_id}            → current snapshot
POST /api/v1/workflow-runs/{run_id}/messages   → 202
PATCH /api/v1/proposals/{proposal_id}           → 202 + new ETag
```

Assert idempotent replay, stale/missing `If-Match`, wrong state, Employee 403,
foreign resource non-disclosure and safe provider/workflow errors.

- [ ] **Step 4: Implement typed routes and composition**

Keep `create_app` injectable. App state holds services/interfaces, not provider
SDK objects used directly by routes. Update CORS headers/methods only as needed by
the public contract.

- [ ] **Step 5: Write and implement SSE replay tests**

Given persisted sequences 1–5 and `Last-Event-ID: 3`, assert only 4–5 stream in
order. Test authorization before response start, heartbeat comments, sanitized
payload and REST recovery after disconnect.

Use `text/event-stream` frames:

```text
id: 4
event: proposal.validating
data: {"proposal_id":"018f6a6a-9f5c-7b12-8c34-1234567890ab","version":2}

```

- [ ] **Step 6: Verify APIs/SSE and stop for review**

```bash
cd backend && uv run pytest tests/test_planning_run_service.py tests/test_planning_run_api_integration.py tests/test_workflow_sse.py -q
cd .. && make lint && make typecheck && make migration-check
```

Expected: PASS.

---

### Task 8: Atomic approval application, stale detection and outbox

**Deliverable:** Manager approval revalidates and applies one exact proposal
version atomically through reusable work-domain commands; rejection has no
business side effect.

**Files:**

- Create: `backend/app/modules/planning_runs/application/approval_service.py`
- Create: `backend/app/modules/planning_runs/application/approval_ports.py`
- Create: `backend/app/modules/planning_runs/adapters/approval_repository.py`
- Create: `backend/app/modules/work/application/shared_commands.py`
- Modify: `backend/app/modules/work/application/project_service.py`
- Modify: `backend/app/modules/work/application/task_service.py`
- Modify: `backend/app/modules/planning_runs/api/routes.py`
- Modify: `backend/app/modules/planning_runs/api/schemas.py`
- Test: `backend/tests/test_approval_service.py`
- Test: `backend/tests/test_approval_api_integration.py`

**Interfaces:**

- Consumes: current immutable proposal version, source references, Task 1 planning
  domain and Phase 1 Project/Task rules.
- Produces: `ApprovalService.decide(...) -> ApprovalDecisionResult` and
  `POST /api/v1/approvals/{approval_id}/decision`.

- [ ] **Step 1: Write service tests for all decision outcomes**

```python
@pytest.mark.asyncio
async def test_reject_records_decision_without_business_rows() -> None:
    result = await service.decide(
        actor=manager,
        approval_id=approval.id,
        decision=ApprovalDecision.REJECT,
        expected_proposal_version=4,
        request_id="req-reject",
        idempotency_key="approval-reject-key",
    )
    assert result.approval.status is ApprovalStatus.REJECTED
    assert transaction.created_business_ids == []
```

Add approve success, duplicate retry, same-key/different-decision conflict,
Employee forbidden, stale proposal, source-version change, deactivated assignee,
validation failure, transaction rollback and already-terminal decision.

- [ ] **Step 2: Extract reusable Phase 1 work commands**

Move shared Project/Task draft validation and authorized write orchestration into
`shared_commands.py`. Existing `ProjectService` and `TaskService` delegate to the
same commands inside their normal single-use-case transactions. Approval invokes
the commands inside one larger `ApprovalTransaction`; it must not call separate
committing services or duplicate domain rules.

Run all existing Project/Task unit and integration tests to prove the refactor
does not change Phase 1 behavior.

- [ ] **Step 3: Implement deterministic source freshness and proposal validation**

Compare every `context_reference` version/fingerprint and the exact proposal
version. Resolve all temporary proposal references before writes. Validate Goal,
Milestone, Task, assignee, date, criterion and dependency graph again in the
approval transaction.

- [ ] **Step 4: Implement the atomic approval repository**

In one SQLAlchemy transaction:

```text
lock approval/proposal version
→ establish/verify tenant
→ apply Project/Goal/Milestone/Task/Criteria/Dependency commands
→ mark approval APPROVED and proposal APPROVED
→ append audit evidence
→ append versioned planning.proposal_approved.v1 outbox event
→ enqueue graph-finalization job
→ commit
```

Any exception rolls back every listed write. Rejected attempts that must be
audited use the established separate safe audit transaction after rollback.

- [ ] **Step 5: Implement and test the decision endpoint**

Require `If-Match` for the proposal version and `Idempotency-Key` for the
decision. Return the approved business IDs only after commit; return structured
412/409/422 errors for stale/version/state/validation failures.

- [ ] **Step 6: Verify approval and stop for review**

```bash
cd backend && uv run pytest tests/test_project_service.py tests/test_task_domain.py tests/test_approval_service.py tests/test_approval_api_integration.py -q
cd .. && make lint && make typecheck && make migration-check
```

Expected: PASS; database assertions prove zero business rows before approval,
exactly one set after approve and zero after reject.

---

### Task 9: SUPERSEDED — do not execute

The file list and steps below are retained only as historical context. They are
not the current product or implementation contract. In particular,
`planning run == conversation`, a recent-run navigator and a page-wide fixed
wizard/stepper are invalid assumptions.

**Deliverable:** Manager/Admin can use the approved full-page AI Planning UX from
natural-language chat through cards, editing, validation/diff and whole-proposal
decision. Employee cannot enter the AI Assistant.

**Files:**

- Create: `frontend/src/features/ai-proposals/contracts.ts`
- Create: `frontend/src/features/ai-proposals/api.ts`
- Create: `frontend/src/features/ai-proposals/event-source.ts`
- Create: `frontend/src/features/ai-proposals/ai-assistant.tsx`
- Create: `frontend/src/features/ai-proposals/run-list.tsx`
- Create: `frontend/src/features/ai-proposals/cards/understanding-card.tsx`
- Create: `frontend/src/features/ai-proposals/cards/assumptions-card.tsx`
- Create: `frontend/src/features/ai-proposals/cards/proposal-card.tsx`
- Create: `frontend/src/features/ai-proposals/cards/validation-card.tsx`
- Create: `frontend/src/features/ai-proposals/cards/approval-card.tsx`
- Create: `frontend/src/features/ai-proposals/proposal-editor.tsx`
- Create: `frontend/src/features/ai-proposals/ai-assistant.test.tsx`
- Create: `frontend/src/features/ai-proposals/api.test.ts`
- Create: `frontend/src/features/ai-proposals/event-source.test.ts`
- Modify: `frontend/src/features/work/workspace.tsx`
- Modify: `frontend/src/features/work/workspace.test.tsx`
- Modify: `frontend/src/shared/i18n/messages/en.json`
- Modify: `frontend/src/shared/i18n/messages/vi.json`
- Modify: `frontend/src/features/work/openapi-contract.json`

**Interfaces:**

- Consumes: Task 7 run/proposal/SSE contracts and Task 8 decision contract.
- Produces: `AiAssistant` and typed query/event helpers used by E2E.

- [ ] **Step 1: Write Zod/API/EventSource contract tests**

Assert all lifecycle enums, proposal provenance, validation severity, allowed
actions and approval result. The event adapter must reconnect and invalidate the
run query after a sequence advance rather than treating SSE data as canonical.

- [ ] **Step 2: Implement contracts and transport helpers**

Expose:

```typescript
startPlanningRun(message: string, locale: "vi" | "en", key: string): Promise<ApiResult<WorkflowRun>>;
getWorkflowRun(runId: string): Promise<WorkflowRunSnapshot>;
editProposal(id: string, content: ProposalContent, version: number, key: string): Promise<ApiResult<Proposal>>;
decideApproval(id: string, decision: "APPROVE" | "REJECT", version: number, key: string): Promise<ApprovalResult>;
```

`event-source.ts` owns `EventSource` creation, status callbacks, reconnect state
and cleanup; it never embeds authorization tokens.

- [ ] **Step 3: Write wizard component tests first**

Cover:

```text
new chat → natural-language submit → queued/running
NEEDS_INPUT → answer card → resume
DRAFT → field/card edit or chat revision
VALIDATING → accessible progress
READY_FOR_DECISION → validation + diff + decision dialog
STALE → disabled approve + reload/revalidate
FAILED → retry + Continue manually
SSE disconnected → reconnect/poll state
```

Assert AI/Manager/Unknown labels, unselected assignee blocking, keyboard/focus
behavior, no confidence display and no raw provider error.

- [ ] **Step 4: Implement the full-page assistant and focused cards**

Activate the existing sidebar `Trợ lý AI` item only for Admin/Manager. Use one
main-canvas page; do not add the persistent small sidebar. Keep cards individually
testable and keep query orchestration in `ai-assistant.tsx`.

- [ ] **Step 5: Implement structured proposal editing and decision flow**

Every saved edit creates a new server version, resets prior validation and waits
for a fresh snapshot. Approval dialog names the exact version and does not show
success until the server confirms the transaction. Rejection navigates to the
terminal read-only run.

- [ ] **Step 6: Add bilingual/accessibility copy and OpenAPI contract updates**

Use the key families approved in UX Spec (`ai.run.status.*`, `ai.card.*`,
`ai.proposal.label.*`, `approval.action.*`, `common.error.stale`). Update the
frontend contract manifest together with FastAPI schemas.

- [ ] **Step 7: Verify frontend and stop for review**

```bash
corepack pnpm@10 --dir frontend test --pool=threads
make lint
make typecheck
```

Expected: PASS with mocked fetch/EventSource and no browser/network dependency.

---

### Task 10: Failure fallback, security fixtures and bilingual evaluation

> **Blocked:** start only after the replacement conversation-first Assistant
> plan is implemented and approved. Task 10 does not repair Task 9 architecture.

**Deliverable:** Every essential AI failure safely falls back, prompt/tool
injection cannot cross policy, retention/tracing behavior is enforced and
`make eval` runs deterministic bilingual golden cases.

**Files:**

- Create: `ai/src/work_management_ai/evaluation/cases.py`
- Create: `ai/src/work_management_ai/evaluation/evaluators.py`
- Create: `ai/src/work_management_ai/evaluation/cli.py`
- Create: `ai/evaluation/planning_golden_vi.jsonl`
- Create: `ai/evaluation/planning_golden_en.jsonl`
- Create: `ai/evaluation/planning_injection.jsonl`
- Create: `ai/tests/test_evaluation.py`
- Create: `backend/tests/test_ai_security_integration.py`
- Create: `backend/tests/test_ai_retention.py`
- Modify: `Makefile`
- Modify: `backend/Makefile`
- Modify: `README.md`

**Interfaces:**

- Consumes: Model Gateway, planning graph/verifier, policy and persistence.
- Produces: deterministic `make eval`, redaction/retention jobs and documented
  local mock/OpenAI/LangSmith configuration.

- [ ] **Step 1: Write fallback/security tests**

Cover provider disabled, timeout, malformed schema twice, verifier rejection,
LangSmith exception, prompt self-approval, fake Admin claim, foreign tenant ID,
system-prompt extraction request, obfuscated injection and HTML/Markdown output.

Assert:

```text
no unauthorized tool call
no business row
safe public error/reference ID
editable manual/proposal path available
audit/model invocation metadata present
no secret or hidden reasoning persisted
```

- [ ] **Step 2: Implement redaction, retention and safe rendering boundaries**

Raw prompt/context rows have explicit expiry no later than 30 days. Redacted
trace metadata expires no later than 90 days. Retention cleanup never deletes
Proposal, Approval, Audit or Outbox business evidence. LangSmith exceptions are
caught by the trace adapter and recorded only as a safe observability failure.

- [ ] **Step 3: Write evaluation tests and golden files**

Each JSONL case contains `case_id`, `locale`, `input`, `mock_output`,
`expected_errors`, `expected_warnings` and `expected_policy_outcome`. Do not use
raw production examples. Test schema validity, required coverage, goal alignment,
dependency validity, testable Criteria, assumptions, unsupported capability,
injection and fallback activation.

- [ ] **Step 4: Implement deterministic evaluators and CLI**

The CLI exits non-zero when any required golden assertion fails and prints only
aggregate/case IDs, not sensitive prompt content. Add:

```make
eval:
	$(MAKE) --no-print-directory -C backend eval
```

Backend `eval` runs the AI evaluation module with the deterministic mock provider.

- [ ] **Step 5: Document local/provider/tracing modes**

README commands must show:

```text
make dev
make worker-dev
make eval
```

Document mock as the default demo/test mode, OpenAI as explicit opt-in and
LangSmith tracing as optional/non-blocking. Never place sample real credentials
in tracked files.

- [ ] **Step 6: Verify security/evaluation and stop for review**

```bash
make eval
cd backend && uv run pytest tests/test_ai_security_integration.py tests/test_ai_retention.py -q
cd .. && make lint && make typecheck && make test
```

Expected: PASS without OpenAI or LangSmith credentials.

---

### Task 11: Phase 2 E2E, contract closure and final verification

> **Blocked:** the E2E and closure steps below must be revised by the replacement
> plan before execution. Phase 2 cannot close against the superseded Task 9 UI.

**Deliverable:** The complete Manager planning flow, rejection and fallback run
through the real API, PostgreSQL, worker and Next.js UI using the mock provider;
all Phase 2 Definition of Done gates have current evidence.

**Files:**

- Create: `frontend/e2e/ai-planning-flow.spec.ts`
- Create: `frontend/e2e/manual-planning-fallback.spec.ts`
- Create: `frontend/scripts/run-e2e.mjs`
- Modify: `frontend/package.json`
- Modify: `frontend/playwright.config.ts`
- Modify: `frontend/src/features/work/openapi-contract.json`
- Modify: `backend/tests/test_frontend_openapi_contract.py`
- Modify: `README.md`
- Modify only when every gate passes: `PLAN.md`

**Interfaces:**

- Consumes: every prior task.
- Produces: complete Phase 2 evidence and, only after all gates pass, an accurate
  Phase 2 closure record in `PLAN.md`.

- [ ] **Step 1: Write the primary AI Planning E2E**

```typescript
test("Manager edits and approves an AI planning proposal", async ({ page }) => {
  await loginAsManager(page);
  await page.getByRole("button", { name: "Trợ lý AI" }).click();
  await page.getByRole("textbox", { name: "Tin nhắn" }).fill(
    "Lập kế hoạch dự án AI-native xuất nhập khẩu",
  );
  await page.getByRole("button", { name: "Gửi" }).click();
  await expect(page.getByText("AI proposal")).toBeVisible();
  for (const assignee of await page.getByRole("combobox", { name: "Người thực hiện" }).all()) {
    await assignee.selectOption({ label: "Demo Employee" });
  }
  await page.getByLabel("Hạn chót", { exact: true }).first().fill("2026-09-25");
  await page.getByRole("button", { name: "Lưu thay đổi" }).click();
  await page.getByRole("button", { name: "Xem lại và duyệt" }).click();
  await expect(page.getByText("Không có lỗi chặn")).toBeVisible();
  await page.getByRole("button", { name: "Duyệt kế hoạch" }).click();
  await page.getByRole("button", { name: "Xác nhận duyệt" }).click();
  await expect(page.getByText("Kế hoạch đã được tạo")).toBeVisible();
  await page.getByRole("button", { name: "Projects" }).click();
  await page.getByRole("button", { name: "AI-native xuất nhập khẩu" }).click();
  await page.getByRole("tab", { name: "Kế hoạch" }).click();
  await expect(page.getByRole("heading", { name: "Mục tiêu dự án" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Milestones" })).toBeVisible();
  await expect(page.getByText("Demo Employee").first()).toBeVisible();
});
```

- [ ] **Step 2: Write rejection and provider-failure E2E scenarios**

Rejection asserts no proposed Project/Goal/Milestone/Task records. Fallback runs
with provider disabled, completes manual Project Plan CRUD and proves the manual
UI does not depend on worker/model availability.

- [ ] **Step 3: Start the worker in the Playwright stack**

`run-e2e.mjs` starts the worker with the E2E database and mock provider, starts
Playwright, forwards termination signals and always stops the child worker. Keep
API/frontend startup under the existing Playwright web-server configuration.
The E2E database reset/migration/seed remains in the root Makefile.

- [ ] **Step 4: Refresh and verify the public OpenAPI manifest**

Ensure every frontend-used enum/schema matches FastAPI exactly. Run:

```bash
cd backend && uv run pytest tests/test_frontend_openapi_contract.py -q
```

Expected: PASS with no ignored schema differences.

- [ ] **Step 5: Run the complete Phase 2 gate**

Run each command separately and preserve its actual output counts:

```bash
make lint
make typecheck
make test
make migration-check
make eval
make test-e2e
```

Expected: every command exits 0. Also confirm no live-provider test ran and no
Phase 2 explicit non-goal appears in dependency or source scans.

- [ ] **Step 6: Perform the final non-goal and data-safety audit**

```bash
rg -n "qdrant|graphrag|celery|redis|kubernetes|jenkins|mlflow" \
  backend ai frontend Makefile compose.yaml
rg -n "chain.of.thought|reasoning_content|api[_-]?key" backend ai frontend
```

Review each hit; expected hits are configuration/negative tests or dependency
metadata only, never an activated forbidden capability or credential.

- [ ] **Step 7: Update closure documentation only after all gates pass**

Record exact command results and counts in `PLAN.md`, update README demo steps and
state explicitly that this closes Phase 2 only. Do not activate Phase 3 or mark
the Core MVP complete.

- [ ] **Step 8: Stop for final user review**

Report files changed, migrations added, dependency lock changes, tests/evals/E2E
run, any live-provider behavior not verified and the result of the explicit
non-goal audit. Do not commit or push without a new explicit instruction.

---

## Execution checkpoints

Execute strictly in this order:

```text
Task 1 backend manual planning
→ Task 2 frontend manual planning (manual slice complete)
→ Task 3 AI package/gateway
→ Task 4 persistence
→ Task 5 worker
→ Task 6 planning graph
→ Task 7 run/proposal/SSE API
→ Task 8 approval transaction
→ replacement conversation-first Assistant foundation and frontend
→ Task 10 fallback/security/evaluation
→ Task 11 E2E/closure
```

After each task, provide the user with:

- Exact changed files.
- Exact commands and outcomes.
- Any unverified behavior.
- Confirmation that unrelated dirty files were preserved.
- A request to approve starting the next task.

Do not compress multiple review checkpoints into one implementation batch unless
the user explicitly changes the requested control level.
