# Solo Developer Execution Plan

## 1. Execution Rules

This plan is an implementation sequence, not a restatement of the full architecture. Product intent and long-term architecture remain documented in `AI_Native_Work_Management_System_Description.md`.

The implementation rules are:

- Build one vertical slice at a time. Every phase must produce an independently demonstrable user outcome.
- Complete and stabilize Core MVP Phases 1–5 before starting optional integrations or the deployment track.
- Keep the runtime as a FastAPI modular monolith with one worker using the same
  business-domain and AI packages. A separate source module does not imply a
  separately deployed AI microservice.
- Keep PostgreSQL as the source of truth. Chat state, model context and retrieval indexes are never authoritative business state.
- Expose AI through one full-page, conversation-first Assistant available to
  every authenticated role. The Assistant infers intent and routes each turn to
  a bounded workflow, Skill or typed read tool; users never select an internal
  workflow manually.
- Keep capability and authorization boundaries role-aware. A shared chat shell
  does not grant every role the same tools, data or mutation permissions.
- Place every HTTP API under `/api/v1`.
- Manager actions performed manually are written directly after authorization, validation and audit. They do not require an approval record by default.
- Approval is mandatory for AI-proposed writes, external side effects, bulk changes and high-risk actions.
- All AI writes are proposals until a human approves them.
- Use deterministic code for authorization, business invariants, calculations, ranking and verification. LLMs may extract, draft or explain, but cannot override deterministic results.
- Use a provider-neutral Model Gateway. The MVP uses an OpenAI hosted API plus a deterministic mock provider for local and automated tests.
- Do not add Calendar, Qdrant, Kubernetes, Jenkins, GKE, self-hosting, distillation or GraphRAG to a Core MVP phase.

### 1.1. Repository ownership and AI engineering emphasis

The repository has three primary product-code boundaries:

- `backend/` owns FastAPI transport, business domain/application services,
  authorization, transactions, PostgreSQL adapters, migrations and audit.
- `ai/` is the first-class AI engineering module. From Phase 2 onward it owns
  the Model Gateway, provider adapters, versioned prompts, structured model
  schemas, workflow graphs, skills, AI tools, verifiers, traces and evaluation.
- `frontend/` is the supporting product/demo surface for manual flows, structured
  AI proposals, evidence, approval and feedback.

System operations remain intentionally small: root Docker Compose supports local
Core MVP development; `deploy/` is still forbidden until the Core MVP Exit Gate.

`ai/` is a separate Python package boundary in the same repository and runtime.
Local development gives `backend/` and `ai/` separate `.venv` directories so
each package proves its declared dependencies independently. `ai/uv.lock` owns
the isolated AI quality environment; `backend/uv.lock` remains the integrated
runtime lock and installs `ai/` as an editable package for API/worker integration
tests. Dependency and execution rules are:

```text
FastAPI composition root / worker
→ AI workflow or backend application service
→ typed application ports
→ deterministic backend services and external adapters
```

- Backend domain code must never import model-provider, agent-framework or AI
  workflow implementations.
- AI tools call typed backend application services; they never write PostgreSQL
  directly or bypass authorization, approval, tenant context and audit.
- The API process and worker may import `ai/`; `ai/` is not deployed as an
  independent network service during Core MVP.
- Do not create `ai/` during Phase 1. Introduce it only when Phase 2 activates
  the first evaluated AI workflow.

Local Docker builds preserve the same boundaries without introducing a Core MVP
microservice:

- `frontend` is an independently built Next.js container.
- `backend-api` is an independently built FastAPI container on port `8000`.
- Before the Task 5 worker exists, the independently built AI image is a
  short-lived `ai-check` quality container only; it must not run a placeholder
  daemon or expose a network port.
- Task 5 changes that image's runtime role to `ai-worker`, which runs the single
  PostgreSQL-backed worker entrypoint, imports the integrated backend/AI packages
  and exposes no HTTP port.
- Container files and local Compose commands are development boundaries, not the
  Post-MVP Deployment Track. Do not create `deploy/` or production deployment
  automation here.

## 2. Core MVP

### Phase 1 — Manual Project/Task Core

> **Status: COMPLETE — 2026-08-01.** The Phase 1 outcome and all applicable
> Global Definition of Done gates have been verified. Phase 2 remains inactive
> until it is explicitly requested.

#### User-visible outcome

A Manager can sign in, create a project, create and assign tasks, and update project/task details directly. An Employee can see assigned tasks and update their status. This phase is a usable manual task manager without AI.

#### Scope

- Initialize the Next.js frontend, FastAPI backend, PostgreSQL migrations and local Docker Compose environment.
- Implement local database-backed authentication for development and portfolio
  demonstration, with seeded Admin, Manager and Employee accounts. Store only
  password hashes and keep the authentication adapter boundary replaceable.
- Establish Organization membership and the Manager/Employee authorization
  roles. In Phase 1, the seeded Admin persona has Manager-equivalent work
  permissions and no separate administration UI.
- Implement Project and Task CRUD, task assignment and a small fixed task-status workflow.
- Provide Manager project/task views and an Employee “My Tasks” view.
- Enforce tenant context, authorization, Row-Level Security and audit logging.
- Write manual Manager changes directly after validation; do not create unnecessary approval requests.

#### Main files/modules

- `frontend/`: application shell, authentication, projects, tasks and My Tasks features.
- `backend/app/modules/identity` and `backend/app/modules/organization`.
- `backend/app/modules/work`: Project, Task and status behavior.
- `backend/alembic/`: schema, indexes and RLS policies.
- No `ai/` package yet; Phase 1 proves the manual business and governance path
  that later AI tools must reuse.

#### Database and API

Database entities:

- `organizations`
- `users`
- `memberships`
- `auth_sessions`
- `projects`
- `tasks`
- `task_status_transitions`
- `audit_events`
- `idempotency_records`

Required APIs:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`
- `GET /api/v1/members`
- `GET /api/v1/projects`
- `POST /api/v1/projects`
- `GET /api/v1/projects/{project_id}`
- `PATCH /api/v1/projects/{project_id}`
- `GET /api/v1/tasks`
- `POST /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `PATCH /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/status`
- `GET /api/v1/my-tasks`

Every tenant-owned table, index, unique constraint and background payload must include tenant context. Application database roles must not use `BYPASSRLS`.

#### Tests

- Project, task, assignment and status domain tests.
- Local login, invalid credential, logout and session tests.
- Admin/Manager/Employee API authorization matrix.
- Cross-tenant API and PostgreSQL RLS negative tests.
- Migration verification.
- Audit coverage and idempotency tests for mutations.
- Frontend component tests and one end-to-end Manager-to-Employee task flow.

#### Definition of Done

- A Manager can create a project and assign a task through the UI.
- An Employee can see only permitted tasks and update status.
- A manual Manager mutation succeeds without an approval record and always creates an audit event.
- Cross-tenant access is blocked at both API and database layers.
- The full phase runs locally with seeded demo accounts and without an external
  identity provider, AI credential or Google credential.

#### Explicit non-goals

- Goal, milestone, dependency and acceptance criteria.
- Skills, capacity, workload or recommendation.
- Daily updates, blocker, risk, reports or feedback.
- Agent Harness, Model Gateway and LLM calls.
- Public registration, account recovery, OIDC/SSO, MFA and user-administration UI.
- Calendar, retrieval infrastructure and deployment automation.

#### Closure record — 2026-08-01

Phase 1 was closed after the following evidence passed against the completed
manual vertical slice:

- `make lint`: Ruff and ESLint passed.
- `make typecheck`: Pyright reported zero errors/warnings and TypeScript passed.
- `make test`: 54 backend unit tests and 33 frontend component/contract tests
  passed.
- `make migration-check`: PostgreSQL reached Alembic revision `0004` (head),
  autogenerate detected no schema drift, and all 10 integration tests passed.
- `make test-e2e`: the production Next.js build passed and both Playwright
  scenarios passed, including the Manager-to-Employee assignment/completion
  flow and invalid-login recovery.
- Project and Task integration coverage verifies role authorization, rejected
  mutations, audit evidence, idempotent replay, optimistic concurrency and
  cross-tenant denial at the API boundary.
- Schema integration coverage verifies RLS default-deny, FORCE RLS,
  tenant-qualified references and cross-tenant denial in PostgreSQL.
- The seeded local demo runs without external identity, AI or Google
  credentials. No `ai/`, Calendar, Qdrant, deployment automation or other
  Phase 1 Explicit non-goal was introduced.

This closes Phase 1 only. It does not activate Phase 2 or the Core MVP Exit Gate.

### Phase 2 — Conversation-First AI Assistant and Planning Proposal

#### User-visible outcome

A full-page AI Assistant is available to every authenticated user as a normal
conversation. An Employee can ask read-only questions about permitted Projects,
assigned Tasks, status, deadlines, dependencies and Acceptance Criteria. A
Manager can additionally enter a natural-language goal, receive an editable
project/task proposal inline in the conversation, and approve or reject it
before any AI-proposed business records are written. Manual planning remains
available outside chat.

#### Scope

- Add Goal, Milestone, Task Dependency and Acceptance Criteria to the manual work-management UI and domain.
- Manual Manager changes use the direct authorized/audited write path.
- Add the provider-neutral Model Gateway with OpenAI hosted and mock providers.
- Add tenant-owned conversations, immutable user/assistant messages and durable
  assistant turns. A conversation may contain multiple turns and may invoke
  zero or more workflow runs.
- Add the minimum conversation-level Agent Harness: a bounded intent router,
  context builder, policy guard, typed read tools, planner/executor, verifier,
  checkpoint and human approval gate.
- In Phase 2 the router supports read-only Project/Task Q&A for every permitted
  role and the planning intent for Admin/Manager. It returns an explicit safe
  availability response for capabilities owned by later phases.
- Implement one goal-to-project-plan workflow with structured output.
- Reuse Phase 1 application services for approved project/task writes.
- Render questions, progress, assumptions, validation errors, before/after
  content and approval actions as assistant messages and structured cards in the
  chat transcript.
- Return an editable manual form when the model or verifier fails.

#### Main files/modules

- Frontend `planning`, `ai_assistant` and reusable assistant-card features.
- Backend `assistant` module for conversation/message/turn persistence, routing,
  read-only tool orchestration and conversation event streaming.
- Backend `work/planning` domain additions, proposal persistence and approval
  application services.
- `ai/model_gateway`: provider-neutral contracts plus hosted OpenAI and
  deterministic mock adapters.
- `ai/prompts` and `ai/schemas`: versioned bilingual prompts and typed structured
  outputs.
- `ai/orchestration`: bounded intent classification and capability selection
  behind the shared Assistant.
- `ai/workflows/planning`: typed state, graph, policy boundary, verifier,
  checkpoint and manual fallback.
- `ai/evaluation`: planning golden cases, malformed-output, timeout and injection
  evaluation fixtures.

#### Database and API

Database entities:

- `assistant_conversations`
- `assistant_messages`
- `assistant_turns`
- `assistant_events`
- `goals`
- `milestones`
- `task_dependencies`
- `acceptance_criteria`
- `proposals`
- `approvals`
- `workflow_runs`
- `workflow_checkpoints`
- `model_invocations`
- `context_references`

Required APIs:

- `POST /api/v1/ai/conversations`
- `GET /api/v1/ai/conversations`
- `GET /api/v1/ai/conversations/{conversation_id}`
- `POST /api/v1/ai/conversations/{conversation_id}/messages`
- `GET /api/v1/ai/conversations/{conversation_id}/events`
- CRUD under `/api/v1/goals`
- CRUD under `/api/v1/milestones`
- CRUD under `/api/v1/task-dependencies`
- CRUD under `/api/v1/acceptance-criteria`
- `POST /api/v1/ai/planning-runs`
- `GET /api/v1/workflow-runs/{run_id}`
- `GET /api/v1/workflow-runs/{run_id}/events`
- `PATCH /api/v1/proposals/{proposal_id}`
- `POST /api/v1/approvals/{approval_id}/decision`

#### Tests

- Conversation/message/turn lifecycle, ordering, idempotency and SSE replay.
- Intent routing for read-only Q&A, planning and unavailable future capability.
- Employee read-only Task/Project Q&A with negative cross-tenant and
  unauthorized-field cases.
- Manual goal/milestone/dependency/criteria CRUD and authorization.
- Dependency-cycle and date-invariant tests.
- Model Gateway adapter contract tests using the mock provider.
- Planning workflow node, branch, pause and resume tests.
- Structured-output and proposal-schema validation.
- Approve, edit, reject, stale proposal and idempotent replay tests.
- Bilingual golden cases and prompt-injection cases.

#### Definition of Done

- Every authenticated role can open the same full-page Assistant, create or
  resume a conversation and receive an inline assistant response without
  selecting a workflow.
- Employee Q&A returns only permitted existing Project/Task facts and cannot
  mutate Project, plan, assignment or approval state.
- A planning turn appears as messages and inline cards in the conversation;
  workflow progress does not replace the transcript with a planning dashboard.
- Manual planning remains fully usable when the model provider is unavailable.
- No Project, Milestone or Task is created from AI output before Manager approval.
- Approval commits the proposal once through existing domain services and creates audit/outbox records.
- Rejection has no business side effect.
- Every AI run records workflow, model, prompt and verifier versions without storing chain-of-thought.
- Invalid output falls back to an editable manual planning form.

#### Explicit non-goals

- Skills, capacity and assignee recommendation.
- Persisting AI-extracted daily updates, risk or report generation. The shared
  Assistant may identify these intents but must return a safe availability card
  until their owning phase is activated.
- An unrestricted general-purpose agent, autonomous execution or a multi-agent
  swarm.
- Qdrant, GraphRAG and document ingestion.
- Calendar integration.
- Self-hosted inference or training.

### Phase 3 — Skills, Capacity and Assignee Recommendation

#### User-visible outcome

A Manager can maintain Employee skills, capacity and leave, inspect workload, and request a ranked assignee recommendation. Ranking is deterministic; AI produces only an evidence-based explanation. The Manager can still assign a task manually without an approval request.

#### Scope

- Add Employee skills, skill evidence, capacity and leave.
- Add deterministic workload calculation.
- Add deterministic candidate hard filtering and weighted scoring.
- Add versioned `recommend_assignee` and `analyze_workload` skills.
- Register assignment/workload intents with the existing Assistant so the
  recommendation and evidence cards appear in the same conversation transcript.
- Use an LLM only to explain scores, evidence, risks and alternatives.
- Require Manager approval only when applying an AI recommendation.
- Preserve a direct authorized/audited manual assignment path.
- Capture accept, override and reject feedback for recommendations.

#### Main files/modules

- Frontend `people`, `capacity`, `workload` and recommendation-card features.
- Backend `people_capacity` module.
- Backend `planning/assignment` deterministic filtering, ranking and assignment
  application services.
- `ai/skills/recommend_assignee` and `ai/skills/analyze_workload`.
- `ai/workflows/assignment_explanation` for evidence-based explanations that
  cannot alter deterministic eligibility or scores.

#### Database and API

Database entities:

- `skills`
- `person_skills`
- `skill_evidence`
- `capacity_entries`
- `leave_entries`
- `recommendations`
- `candidate_scores`
- `recommendation_feedback`
- `skill_versions`

Required APIs:

- CRUD under `/api/v1/skills`
- CRUD under `/api/v1/members/{member_id}/skills`
- CRUD under `/api/v1/capacity`
- CRUD under `/api/v1/leave`
- `GET /api/v1/workload`
- `POST /api/v1/tasks/{task_id}/assign`
- `POST /api/v1/tasks/{task_id}/assignee-recommendations`
- `GET /api/v1/recommendations/{recommendation_id}`
- `POST /api/v1/recommendations/{recommendation_id}/approve`
- `POST /api/v1/recommendations/{recommendation_id}/feedback`

#### Tests

- Capacity, leave and workload calculation tests.
- Candidate hard-constraint and score-reproducibility tests.
- Permission tests for profile evidence and assignments.
- Proof that an LLM response cannot alter candidate scores or eligibility.
- Manual assignment without approval versus AI recommendation approval.
- Provider-failure fallback to an unexplained deterministic ranking.
- Recommendation acceptance, override and feedback tests.

#### Definition of Done

- The same inputs always produce the same ranking and score breakdown.
- An ineligible candidate cannot be approved even if named by the model.
- Manager can see evidence and workload behind each candidate.
- A manual assignment writes immediately after authorization and audit.
- An AI-recommended assignment requires explicit Manager approval.
- Recommendation remains usable when explanation generation fails.
- The Assistant routes a permitted assignment/workload request to the Phase 3
  capability without creating a second chat product or exposing workflow
  selection to the user.

#### Explicit non-goals

- Google Calendar availability.
- CP-SAT or portfolio-wide optimization.
- Learned ranking, effort estimation or performance scoring.
- Automatic assignment and autonomous replanning.

### Phase 4 — Manual and AI Daily Update, Blocker and Risk

#### User-visible outcome

An Employee can submit a daily update either through a structured manual form or natural-language extraction. The Employee confirms AI extraction before saving. A Manager can see blockers and deterministic risk with an optional AI explanation.

#### Scope

- Add manual daily updates with done, blocker and next-step items.
- Add evidence, work logs and blocker lifecycle.
- Add deterministic risk rules based on deadlines, dependencies, activity and blocker age.
- Add AI extraction, task-link suggestions and blocker classification.
- Register daily-update and blocker/risk intents with the existing Assistant.
  Employee messages produce a structured `Done / Blockers / Next steps` card
  that the Employee must correct or confirm before persistence.
- Surface confirmed blockers and their evidence to permitted Managers. The
  Assistant may notify or recommend a response, but it cannot edit the plan,
  assignment or deadline autonomously.
- Require Employee confirmation before persisting extracted content.
- Use the model only to explain deterministic risk factors.
- Add thresholded and deduplicated in-app risk notifications.
- Keep the whole flow usable through manual forms when AI is unavailable.

#### Main files/modules

- Frontend `daily_updates`, `blockers` and `risk` features.
- Backend `progress` module.
- Backend `risk` module for deterministic risk inputs, rules and persistence.
- `ai/workflows/daily_update` for extraction and task-link suggestions.
- `ai/workflows/risk_explanation` for explanations over verified stored factors.
- `ai/evaluation/daily_update` for bilingual extraction, malformed output and
  provider-failure cases.

#### Database and API

Database entities:

- `daily_updates`
- `daily_update_items`
- `work_logs`
- `evidence`
- `blockers`
- `risk_assessments`
- `notifications`

Required APIs:

- `POST /api/v1/daily-updates`
- `GET /api/v1/daily-updates`
- `POST /api/v1/daily-updates/extract`
- `POST /api/v1/daily-updates/{draft_id}/confirm`
- CRUD under `/api/v1/blockers`
- `GET /api/v1/risks`
- `POST /api/v1/risks/{risk_id}/explain`
- `GET /api/v1/notifications`

#### Tests

- Manual daily-update and blocker lifecycle tests.
- Bilingual extraction and task-linking evaluation cases.
- Employee correction and low-confidence fallback tests.
- Deterministic risk score reproduction and dependency-impact tests.
- Proof that AI explanation cannot mutate a risk score.
- Notification threshold and deduplication tests.
- Provider timeout and malformed-output fallback tests.

#### Definition of Done

- Manual daily update, blocker and risk views work without a model provider.
- AI-extracted data is not persisted until Employee confirmation.
- A reported completion cannot bypass deterministic task completion rules.
- Every risk score is reproducible from stored inputs and rule version.
- Every AI explanation references stored risk factors and evidence.
- AI failure never blocks manual submission or Manager risk review.
- Employee daily-update turns and Manager blocker review remain in the same
  conversation-first Assistant while respecting their different permissions.

#### Explicit non-goals

- Trained risk or effort model.
- Automatic task completion, assignment or replanning.
- External notifications.
- Management report narrative.
- Calendar and knowledge retrieval.

### Phase 5 — Management Report, Feedback and Evaluation Loop

#### User-visible outcome

A Manager can generate and review daily or weekly management reports. Numbers come from deterministic queries; AI can draft the narrative. Users can submit accept, edit or reject feedback, and the developer can run a versioned evaluation suite against accumulated permission-safe cases.

#### Scope

- Create deterministic daily and weekly report metric snapshots.
- Generate an optional LLM narrative from an immutable snapshot.
- Register project-status and management-report intents with the existing
  Assistant; responses render verified metric/evidence cards inline and may link
  to the full report view.
- Verify every narrative number against the snapshot.
- Require Manager review before publishing an AI-authored report.
- Allow direct publishing of a deterministic metrics-only report.
- Capture feedback with proposal/run/model/prompt/skill versions and later actual outcome.
- Redact and retain raw AI context for 30 days and redacted traces for 90 days.
- Add a small golden evaluation suite and an automated evaluation command.
- Add a transactional outbox worker for report generation, notification and retention jobs.

#### Main files/modules

- Frontend `reports`, `feedback` and minimal evaluation-status views.
- Backend `reporting` and `feedback` modules.
- Backend outbox worker, immutable metric snapshot and feedback persistence.
- `ai/workflows/reporting` for verified narrative generation.
- `ai/evaluation` for the versioned golden suite, evaluators and promotion gates.
- `ai/observability` for model/workflow/prompt/skill version and trace contracts.

#### Database and API

Database entities:

- `reports`
- `report_metric_snapshots`
- `feedback`
- `evaluation_cases`
- `evaluation_results`
- `outbox_events`
- Retention metadata on AI run/context records.

Required APIs:

- `POST /api/v1/reports`
- `POST /api/v1/reports/{report_id}/generate-narrative`
- `GET /api/v1/reports/{report_id}`
- `POST /api/v1/reports/{report_id}/publish`
- `POST /api/v1/feedback`
- `POST /api/v1/evaluations/runs`
- `GET /api/v1/evaluations/runs/{run_id}`

#### Tests

- Report aggregation and immutable-snapshot tests.
- Narrative numeric-consistency and unsupported-claim tests.
- Metrics-only fallback tests.
- AI report approval versus manual report publishing tests.
- Feedback provenance, redaction, deduplication and retention tests.
- Outbox retry and idempotent consumer tests.
- Core bilingual golden evaluation suite.
- End-to-end Core MVP flow from Manager project creation through feedback.

#### Definition of Done

- Every report number is traceable to an immutable metric snapshot.
- Invalid AI narrative is rejected or replaced by the metrics-only report.
- AI-authored reports require Manager approval; manual metrics reports do not.
- Feedback links input, output, versions, human correction and available outcome.
- Retention jobs delete expired raw context without deleting required business audit records.
- Phases 1–5 pass one automated end-to-end Core MVP scenario in Vietnamese and English.
- One conversation can route successive permitted planning, status, daily-update
  and reporting turns without exposing internal workflow names or granting
  cross-role capabilities.

#### Explicit non-goals

- Qdrant, hybrid retrieval and GraphRAG.
- Google Calendar or other external integrations.
- Kubernetes, Jenkins and GKE.
- Model training, self-hosting, distillation and learned optimization.

## 3. Core MVP Exit Gate

Optional integrations and the deployment track may start only when:

- All Phase 1–5 Definitions of Done pass.
- The manual product remains usable when all AI providers are disabled.
- All AI writes require human approval.
- Cross-tenant leakage and approval bypass tests report zero violations.
- All state-changing APIs are authorized, validated, idempotent where retryable, transactional and audited.
- Core workflow failure and fallback paths have automated tests.
- The Core MVP has been demoed end to end without unresolved severity-high defects.

## 4. Post-MVP Optional Integrations

These integrations are independent. Neither blocks the deployment track.

### I1 — Google Calendar

#### User-visible outcome

A Manager can include Google Calendar availability in assignment review and create an event after an assignment is approved.

#### Scope

- Google OAuth testing mode with a personal account during development.
- Availability lookup and event creation only.
- Google and mock adapters sharing one typed contract.
- Encrypted token storage, freshness indicators, retry and idempotency.
- External event creation always requires explicit approval.

#### Main files/modules

- Frontend integration settings and assignment availability UI.
- Backend `integrations/calendar` module.
- Google Calendar and mock adapters.

#### Database and API

Database entities:

- `calendar_connections`
- `availability_snapshots`
- `external_event_mappings`

APIs:

- `GET /api/v1/integrations/google-calendar/connect`
- `GET /api/v1/integrations/google-calendar/callback`
- `GET /api/v1/calendar/availability`
- `POST /api/v1/tasks/{task_id}/calendar-events`

#### Tests

- Adapter contract, OAuth expiry/revocation, token isolation, stale availability, duplicate event and provider-outage tests.

#### Definition of Done

- Calendar failure does not block assignment.
- Event creation is idempotent and occurs only after approval.
- Local and automated tests run without Google credentials.

#### Explicit non-goals

- Gmail, domain-wide delegation, two-way task sync and automatic rescheduling.

### I2 — Qdrant Hybrid Knowledge Retrieval

#### User-visible outcome

Users can find permitted organizational documents and receive an evidence-backed answer with citations.

#### Scope

- Document upload/versioning and object storage.
- Permission-aware indexing.
- Qdrant hybrid retrieval with tenant and permission metadata filters.
- Citation validation and evidence-only fallback.
- Direct PostgreSQL queries remain mandatory for transactional facts.

#### Main files/modules

- Frontend knowledge search and citation viewer.
- Backend `knowledge` module for canonical document metadata and permission
  enforcement.
- `ai/retrieval` for indexing, hybrid query, reranking and citation verification.
- Qdrant and object-storage adapters behind typed ports.

#### Database and API

Database entities:

- `documents`
- `document_versions`
- `document_chunks`
- `citations`
- `indexing_jobs`

APIs:

- `POST /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `POST /api/v1/documents/{document_id}/reindex`
- `POST /api/v1/knowledge/search`
- `POST /api/v1/knowledge/answer`

#### Tests

- Retrieval recall, citation validity, tenant leakage, permission revocation, stale version, malicious document and Qdrant-outage tests.

#### Definition of Done

- Permission filtering happens before retrieval results enter model context.
- Every answer claim is cited or reported as insufficient evidence.
- Qdrant never becomes the source of truth for project/task facts.

#### Explicit non-goals

- GraphRAG, knowledge-graph extraction and automatic Work Graph mutation.

## 5. Post-MVP Deployment Track

This track may begin after the Core MVP Exit Gate. It does not wait for I1 or I2.

### D1 — Kubernetes Packaging with kind

#### User-visible outcome

No new product behavior; the stable Core MVP can be installed, upgraded and rolled back in local Kubernetes.

#### Scope

- OCI images for frontend, API and worker.
- Package `ai/` into the API and worker images; do not add an AI network service
  unless a later measured scaling or isolation requirement authorizes it.
- Helm chart with Namespace, Deployments, Services, Gateway/Ingress, ConfigMaps, Secrets, probes, resources, HPA, Jobs/CronJobs, Service Accounts and NetworkPolicies.
- kind integration environment and migration Job.

#### Main files/modules

- `deploy/helm/`
- `deploy/kind/`
- Application container build files.

#### Database and API

- No new business entities or APIs.
- Add `/api/v1/health/live`, `/api/v1/health/ready` and `/api/v1/health/startup`.

#### Tests

- Helm lint/template, kind install, upgrade, rollback, probe, migration Job and NetworkPolicy tests.

#### Definition of Done

- A documented command starts the application on kind.
- Upgrade and rollback preserve database and outbox correctness.
- Runtime behavior matches the Compose environment.

#### Explicit non-goals

- Jenkins, GKE, service mesh, custom operators, GitOps, multi-cluster and GPU workloads.

### D2 — Jenkins CI/CD

#### User-visible outcome

No new product feature; every release candidate is tested, evaluated, scanned and packaged reproducibly.

#### Scope

- Jenkins stages for lint, typecheck, tests, evaluation, dependency/image scan, image build, Helm checks and kind smoke tests.
- Immutable image tags and manual promotion approval.

#### Main files/modules

- `Jenkinsfile`
- Reusable CI scripts and artifact metadata.

#### Database and API

- No business database or API changes.

#### Tests

- Clean-build reproducibility, failure-path, secret-masking and artifact-provenance tests.

#### Definition of Done

- Failed tests, evaluation gates or security scans block promotion.
- Artifacts map to an exact commit and migration version.
- Jenkins and local development use the same quality commands.

#### Explicit non-goals

- Unapproved production deployment, GitOps and Jenkins-owned business migrations.

### D3 — GKE Autopilot

#### User-visible outcome

Pilot users can access the Core MVP through a stable HTTPS staging/production endpoint with monitoring, backup and rollback.

#### Scope

- GKE Autopilot in `asia-southeast1`.
- Managed/dedicated PostgreSQL, Redis, object storage and optional Qdrant outside Kubernetes.
- Workload Identity, Secret Manager, TLS, autoscaling, observability, backup/restore and rolling rollback.

#### Main files/modules

- `deploy/gke/`
- Production Helm values and operations runbooks.

#### Database and API

- No new business entities or APIs.
- Operational metrics and retention Jobs only.

#### Tests

- Staging load/soak, backup restore, pod interruption, migration compatibility, tenant isolation and rollback rehearsal.

#### Definition of Done

- Production uses immutable Jenkins artifacts.
- Backup restore and rollback have recorded evidence.
- No durable state exists only on pod filesystems.
- Agreed availability and latency SLOs are measured.

#### Explicit non-goals

- Service mesh, custom operators, multi-cluster, GPU pools and microservice decomposition.

## 6. Advanced Track

### A1 — Solver and Predictive ML

Activate only after stable historical outcomes, a versioned dataset, a deterministic baseline and a held-out evaluation set exist.

#### User-visible outcome

Managers can compare optimized assignment or replanning options with constraints, confidence and explanations.

#### Scope

- OR-Tools CP-SAT for constrained optimization.
- Tabular effort/risk models only when they outperform deterministic baselines.
- Shadow and canary evaluation before production use.

#### Main files/modules

- `ai/optimization`, `ai/ml` and `ai/evaluation` packages; deterministic hard
  constraints remain owned and verified by backend application/domain code.

#### Database and API

- `optimization_runs`, `simulations`, `feature_snapshots`, `dataset_versions`, `model_versions`.
- `/api/v1/simulations` and `/api/v1/optimization-runs`.

#### Tests

- Solver feasibility, calibration, drift, fairness slices, baseline comparison and rollback tests.

#### Definition of Done

- The new method beats its documented baseline and never violates hard constraints.
- Applying a replan remains a high-risk action requiring human approval.

#### Explicit non-goals

- LLM-based constraint solving, autonomous replanning and Employee performance judgment.

### A2 — Self-hosting and Distillation

Activate only after permission-safe reviewed training data, a bilingual held-out set, governance approval and a demonstrated cost/privacy/latency benefit exist.

#### User-visible outcome

Selected low-risk AI tasks can use a validated student model with hosted-model fallback.

#### Scope

- OpenAI-compatible self-hosted inference adapter.
- Teacher-data curation and SFT/LoRA experiments.
- Offline evaluation, shadow routing and canary promotion.
- Hosted OpenAI fallback when capability or verification fails.

#### Main files/modules

- `ai/model_gateway/adapters/self_hosted`.
- `ai/training`, `ai/evaluation` and versioned routing configuration.

#### Database and API

- `training_runs`, `model_artifacts`, `routing_decisions`.
- Admin-only `/api/v1/model-evaluations` and `/api/v1/model-routes`.

#### Tests

- Teacher/student quality, safety, structured output, load, timeout, fallback and rollback tests.

#### Definition of Done

- Student model passes the declared held-out quality and safety gates.
- Production routing is limited to approved low-risk workflows.
- Hosted fallback is verified under real failure scenarios.

#### Explicit non-goals

- Training on raw production data, immediate replacement of hosted models and MVP-cluster GPU deployment.

### A3 — GraphRAG

Activate only when a labeled multi-hop/global-query benchmark proves that direct query and Qdrant hybrid retrieval are insufficient.

#### User-visible outcome

Users can answer evidence-backed multi-hop or organization-wide relationship questions that the existing retrieval modes cannot answer reliably.

#### Scope

- Versioned knowledge entity/relation extraction.
- Multi-hop/global retrieval workflow.
- Permission propagation and graph-specific evaluation.
- Preserve the separation between inferred Knowledge Graph and verified Work Graph.

#### Main files/modules

- `ai/retrieval/graphrag` indexing/projection and retrieval adapter.
- `ai/evaluation/graphrag` dedicated benchmark and evaluator.

#### Database and API

- `knowledge_entities`, `knowledge_relations`, `graph_index_versions`.
- Extend `/api/v1/knowledge/search` with an explicit evaluated GraphRAG mode.

#### Tests

- Entity/relation quality, multi-hop benchmark, permission propagation, stale-source removal and cost/quality comparisons.

#### Definition of Done

- The benchmark shows a documented, material quality improvement over direct and hybrid retrieval.
- Every generated answer remains permission-filtered, source-versioned and cited.
- Inferred relations never become verified Work Graph facts automatically.
- Simple task, deadline, assignee and exact-document queries continue using direct or hybrid retrieval.
- GraphRAG can be disabled without affecting Core MVP or ordinary knowledge search.

#### Explicit non-goals

- GraphRAG as the default retrieval mode.
- Graph database as the transactional source of truth.
- Automatic mutation of Work Graph from model-inferred relations.

## 7. Global Definition of Done

Every phase or track item is complete only when all applicable conditions pass:

1. The documented user-visible outcome can be demonstrated independently.
2. Lint, formatting checks, type checking, unit tests and integration tests pass.
3. Required end-to-end happy path and failure/fallback paths pass.
4. Database migrations, RLS, tenant indexes and rollback/forward-compatibility have been reviewed.
5. Authorization, audit and idempotency tests cover every new mutation.
6. AI behavior implemented under `ai/` has typed output, deterministic verifier,
   recorded model/prompt/workflow/skill versions, evaluation cases and a non-AI
   fallback where the underlying product flow is essential.
7. Manual writes, AI-proposed writes, bulk changes, external side effects and high-risk actions follow their correct approval policy.
8. Public APIs remain under `/api/v1` and OpenAPI contracts are updated.
9. Local run and demo instructions are current.
10. No phase silently introduces work listed in its Explicit non-goals.
