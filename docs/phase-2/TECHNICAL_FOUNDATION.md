# Phase 2 Technical Foundation — Conversation-First AI Assistant and Planning Proposal

## 1. Status and purpose

This document records the approved technical foundation for Phase 2. It refines
the user experience in `docs/phase-2/UX_SPEC.md` into implementation boundaries,
data contracts, workflow behavior, security controls and verification gates.

This is a design document, not an implementation status record. Phase 2 remains
incomplete until its full Definition of Done in `PLAN.md` passes.

The primary outcome is:

```text
Authenticated user sends a natural-language message in one Assistant conversation
→ API atomically persists the user message and one assistant turn
→ bounded intent router selects permitted read-only Q&A, Manager planning or a
  safe unavailable-capability response
→ a planning turn creates an asynchronous planning run
→ one worker runs the bounded-agentic LangGraph planning workflow
→ AI returns a typed, editable proposal
→ deterministic validation produces errors, warnings and a diff
→ Manager edits, approves or rejects one complete proposal version
→ only a successful approval transaction creates business records
```

Manual planning remains fully usable without an AI provider.

## 2. Approved architecture decisions

### 2.1. Runtime style

Phase 2 uses an asynchronous modular monolith:

- Next.js frontend.
- FastAPI API process.
- One Python worker importing the same domain and application packages.
- PostgreSQL as business source of truth, workflow store, job queue and outbox.
- SSE for one-way progress notification.
- REST for commands, snapshots, polling and recovery.

The AI call is never held open inside the request that creates a planning run.
The API returns `202 Accepted` and a `run_id` immediately. Approval application
is a deterministic, bounded transaction and may complete synchronously in the
decision request; model execution remains asynchronous.

Phase 2 does not add Redis, Celery, Kafka, RabbitMQ or a separate AI network
service. PostgreSQL is sufficient for the single-worker Core MVP boundary.

### 2.2. AI stack

- LangGraph owns planning graph state, nodes, conditional edges, loops,
  checkpoints and human interrupts.
- LangChain is restricted to prompt/message composition, model adapter helpers
  and typed structured output inside `ai/`.
- LangSmith is an optional, non-blocking tracing and evaluation adapter.
- A project-owned Model Gateway is the provider-neutral model boundary.
- The hosted MVP provider is OpenAI through `langchain-openai`.
- A deterministic mock provider is the default for local and automated tests.

The production model is configured, not hard-coded into domain or workflow
behavior.

### 2.3. Bounded-agentic behavior

The workflow is neither a rigid template nor an unrestricted autonomous agent.
It uses a fixed safety envelope with an agentic planning loop inside it:

```text
fixed control plane
├── conversation/turn identity, tenant and permission
├── bounded intent and capability registry
├── context and tool allowlist
├── budgets, retry limits and stop conditions
├── schema and deterministic verification
├── checkpoint and human approval
└── audit and evaluation

agentic planning region
├── understand the goal
├── determine missing information
├── ask contextual questions
├── choose permitted context reads
├── decompose the plan
└── revise the proposal from Manager feedback
```

The model may decide how to structure a plan. It may not decide authorization,
tenant ownership, arithmetic, date validity, dependency cycles, approval policy
or whether a business transaction succeeded.

The conversation-level orchestrator is also bounded. It may classify a turn and
select an allowed capability, but deterministic policy decides whether that
capability exists for the current phase and whether the actor may use it.

### 2.4. Phase boundary

Phase 2 implements the minimum Agent Harness required for a real shared Assistant:

- conversation and turn orchestration;
- `work.read` over existing permitted Project/Task facts;
- `planning.create` for Admin/Manager;
- a deterministic unavailable-capability route for future intents.

This is not an unrestricted general-purpose router, a general Skill Registry, a
multi-agent swarm or a set of named agents. Later phases register their bounded
capabilities with the same harness instead of creating separate chat products.

## 3. Runtime and package boundaries

### 3.1. Runtime flow

```text
Browser
  ↓ same-origin REST/SSE
Next.js
  ↓
FastAPI /api/v1
  ├── Assistant conversation/message/turn service
  ├── bounded intent/capability router
  ├── typed read tools or backend application services
  ├── PostgreSQL transaction/RLS/audit
  └── planning turn: create workflow run + job
                                      ↓
                                Python worker
                                      ↓
                              ai planning graph
                                      ↓
                                 Model Gateway
                              ├── OpenAI adapter
                              └── mock adapter
```

The worker:

1. Claims an available PostgreSQL job using a lease.
2. Establishes the job's tenant context.
3. Loads the current typed checkpoint.
4. Executes the permitted graph step or steps.
5. Persists checkpoint, proposal and public progress events.
6. Marks the job complete, schedules a bounded retry or exposes fallback.

SSE is never the source of truth. A browser can reconstruct the current state
from the conversation REST snapshot after disconnecting or reloading. Planning
workflow snapshots remain available for focused recovery and diagnostics.

### 3.2. Repository boundaries

```text
frontend/
  Next.js UI, REST client, EventSource integration and presentation schemas

backend/app/
  FastAPI, domain, application services, authorization, transactions,
  PostgreSQL adapters, Assistant conversation/turn persistence, typed work reads,
  RLS, audit, idempotency and outbox

ai/
  Model Gateway, provider adapters, prompts, structured model schemas,
  bounded turn routing, planning graph, policy boundary, context builder,
  verifier, traces and eval
```

Dependency rules:

- Backend domain and application code do not import LangGraph, LangChain or a
  model-provider SDK.
- AI code does not import backend database adapters or write PostgreSQL tables
  directly.
- AI tools call typed backend application ports/services.
- Workflow/checkpoint persistence is exposed through typed ports implemented by
  backend infrastructure adapters.
- API and worker composition roots may import both backend and `ai/` packages.
- LangSmith is observational and cannot change a workflow result.

`ai/` is a separate Python package boundary in the same locked workspace and
runtime. It is not deployed as a microservice during Core MVP.

## 4. Planning business model

### 4.1. Entity hierarchy

```text
Project
├── 0..1 Goal (shown as "Mục tiêu dự án")
├── many Milestones
└── many Tasks
    ├── belongs to 0..1 Milestone
    ├── many Acceptance Criteria
    └── dependencies only on Tasks in the same Project
```

Goal remains a separately versioned and audited technical entity, but the UI
does not expose a separate Goals navigation item. It appears within Project
detail and the Project Plan tab.

### 4.2. Domain additions

`Goal` contains:

- `id`, `organization_id`, `project_id`.
- Title and description.
- Expected outcomes.
- Optional target date.
- Resource version and timestamps.

`Milestone` contains:

- `id`, `organization_id`, `project_id`.
- Name and optional description.
- Optional target date.
- Stable display position.
- Resource version and timestamps.

`Task` gains an optional, tenant-qualified `milestone_id`.

`TaskDependency` contains:

- `organization_id`.
- Predecessor and successor Task references.
- Version/audit metadata required by the mutation contract.

`AcceptanceCriterion` contains:

- `id`, `organization_id`, `task_id`.
- Non-empty criterion text.
- Stable display position.
- Resource version and timestamps.

### 4.3. Deterministic invariants

- A Project has at most one Goal.
- Every relation stays inside one organization.
- A Task may reference a Milestone only in the same Project.
- Both ends of a dependency must be Tasks in the same Project.
- A Task cannot depend on itself.
- Duplicate dependency edges are rejected.
- The dependency graph must remain acyclic.
- Acceptance Criteria must be non-empty and unique after normalization within a
  Task.
- When both dates exist, a Task due date cannot be later than its Milestone
  target date.
- AI proposal Tasks require a manually selected, active, same-tenant assignee
  before approval because assignee recommendation belongs to Phase 3.
- Stale-sensitive mutations use resource versions and optimistic concurrency.

Authorization and every invariant are enforced by domain/application code and
database constraints where practical. Prompts and frontend validation may
explain these rules but are not authoritative.

## 5. Proposal, approval and workflow persistence

### 5.1. Conversation, message and assistant-turn model

```text
AssistantConversation
└── AssistantMessage (immutable, ordered USER or ASSISTANT)
    └── AssistantTurn (one per accepted USER message)
        └── 0..1 WorkflowRun in Phase 2
```

- A conversation is a tenant-owned transcript container and may contain many
  intents over time.
- A message is immutable after commit. Assistant messages contain ordered typed
  content blocks such as `text`, `progress`, `work_answer`, `question`,
  `proposal`, `validation`, `approval`, `error` or `availability`.
- A turn records routing and execution metadata for exactly one accepted user
  message. It may complete through typed read tools without a WorkflowRun, or it
  may own one bounded planning WorkflowRun.
- Workflow state/checkpoints are execution detail. They do not replace messages
  and are not rendered as a fixed planning dashboard.
- Conversation history is context, not official business state. Project, Task,
  Proposal, Approval and DailyUpdate tables remain authoritative facts.

Assistant turn lifecycle:

```text
QUEUED → RUNNING → NEEDS_INPUT → RUNNING → COMPLETED
                  └────────────────────────→ FAILED
```

The API atomically commits a user message, turn, initial safe event and any
required job before returning. An idempotent replay returns the original message
and turn without duplicating work.

### 5.2. Workflow run lifecycle

```text
QUEUED
→ RUNNING
→ NEEDS_INPUT
→ RUNNING
→ WAITING_FOR_DECISION
→ COMPLETED

failure branch: RUNNING → FAILED
```

- `QUEUED`: the API committed a run and job; no worker owns it yet.
- `RUNNING`: a worker is executing a graph node.
- `NEEDS_INPUT`: the graph is paused at a human-input checkpoint.
- `WAITING_FOR_DECISION`: a valid proposal version is waiting for a Manager.
- `COMPLETED`: the proposal was approved and applied, or rejected.
- `FAILED`: bounded retries ended without a usable AI result; fallback remains
  available.

Human waiting time does not consume a worker process or active-runtime budget.

### 5.3. Proposal lifecycle

```text
DRAFT v1
→ VALIDATING
→ READY_FOR_DECISION
→ APPROVED | REJECTED

edit → DRAFT v2
source changed → STALE
```

The Proposal is an aggregate and `proposal_versions` are immutable snapshots.
Each version stores:

- Typed structured plan content.
- Field provenance: `AI_PROPOSED`, `MANAGER_EDITED` or `UNKNOWN`.
- Assumptions and open questions.
- Deterministic validation result.
- Source-reference snapshot.
- Workflow, prompt, schema, model and verifier versions.
- Creator type and timestamp.

An edit creates a new proposal version. It never overwrites the version shown in
a prior diff or approval record.

`STALE` means the proposal is based on source data that is no longer current. It
does not mean the model was necessarily wrong. For example, a proposal validated
against Project version 4 becomes stale if that Project changes to version 5, or
if a selected membership is deactivated. A stale proposal must be refreshed and
revalidated before a decision.

Phase 2 approves or rejects the whole proposal. To exclude a Milestone or Task,
the Manager edits it out, creates a new version, revalidates and then decides.

### 5.4. Approval lifecycle and transaction

```text
PENDING
→ APPROVED | REJECTED | SUPERSEDED
```

An approval references exactly one immutable proposal version. Editing that
proposal supersedes the pending approval for the prior version.

Approve executes:

```text
resolve tenant from authenticated membership
→ authorize actor and enforce RLS
→ evaluate organization/action policy
→ compare expected proposal version
→ verify source freshness
→ rerun deterministic validation
→ apply through business application services
→ write approval, outbox and audit
→ commit once
```

Project, Goal, Milestone, Task, Dependency and Acceptance Criterion records are
visible only after the complete transaction commits. A failed transaction cannot
leave the approval marked approved. An idempotent retry returns the recorded
result without creating duplicate records.

Reject writes the decision and audit evidence but creates no proposed business
records.

The graph is paused at `await_manager_decision`. The approval API performs the
deterministic business transaction synchronously. After commit it schedules a
small job to resume/finalize the graph and publish the final workflow event. The
model is not called during approval application.

### 5.5. Persistence entities

Phase 2 adds the entities required by `PLAN.md`:

- `assistant_conversations`, `assistant_messages`, `assistant_turns`,
  `assistant_events`.
- `goals`, `milestones`, `task_dependencies`, `acceptance_criteria`.
- `proposals`, `approvals`.
- `workflow_runs`, `workflow_checkpoints`.
- `model_invocations`, `context_references`.

The asynchronous and immutable-history design additionally requires:

- `proposal_versions`.
- `workflow_jobs`.
- `workflow_events`.
- `outbox_events`.

All tenant-owned rows have a non-null `organization_id`. Tenant-owned unique
constraints, indexes and references include it.

`assistant_messages` are ordered by a unique tenant-qualified conversation
sequence. `assistant_turns` reference the initiating user message and optional
workflow run. `assistant_events` provide a replayable, UI-safe sequence for
message/turn updates without placing raw model context in public payloads.

### 5.6. PostgreSQL job records

`workflow_jobs` is the queue. A record includes:

```text
id, organization_id, workflow_run_id
job_type, status
attempt_count, max_attempts, available_at
locked_by, lease_expires_at
minimal JSONB payload, last_error_code
created_at, updated_at
```

The payload contains identifiers and the minimum resume instruction, not hidden
reasoning or a duplicate full prompt. A worker claims a job with row locking and
a lease. If the worker crashes, another claim is possible after lease expiry.
Node side effects are idempotent because a resumed node can execute again.

### 5.7. Workflow and Assistant progress records

`workflow_events` is an append-only, UI-safe event stream:

```text
id, organization_id, workflow_run_id
sequence, event_type, public_payload JSONB, occurred_at
```

`(organization_id, workflow_run_id, sequence)` is unique. SSE event IDs use the
sequence. A reconnect with `Last-Event-ID: 12` replays events after sequence 12.
Public payloads contain status, safe labels, resource references and validation
summaries, never provider secrets, stack traces or hidden chain-of-thought.

`assistant_events` use the same append-only sequence and sanitization rules at
conversation scope. A planning worker appends its domain-specific
`workflow_events` and the corresponding safe conversation event/message block in
one transaction where possible. REST reconstruction remains authoritative if an
SSE notification is missed.

### 5.8. Transactional outbox

`outbox_events` stores versioned business events committed with the mutation:

```text
event_id, envelope_version, organization_id
event_type, aggregate_type, aggregate_id
safe payload JSONB, occurred_at
attempt_count, available_at, published_at, last_error_code
```

For approval, business records, approval, audit evidence and the outbox event are
written in one transaction. This prevents a committed business change from being
lost before an event consumer sees it. The same worker may dispatch Phase 2
outbox records; no message broker is introduced.

## 6. API, SSE and concurrency contracts

### 6.1. Assistant conversation APIs

Primary user-facing endpoints:

```text
POST /api/v1/ai/conversations
GET  /api/v1/ai/conversations
GET  /api/v1/ai/conversations/{conversation_id}
POST /api/v1/ai/conversations/{conversation_id}/messages
GET  /api/v1/ai/conversations/{conversation_id}/events
```

Creating a conversation does not select or start a workflow. Posting a message
atomically creates an immutable user message and one assistant turn, then
returns `202 Accepted` with conversation/message/turn references. The server,
not the client, records the selected intent/capability after policy evaluation.

The conversation snapshot contains ordered messages with typed safe content
blocks, current turn states and allowed actions. It may include safe links to a
proposal, approval, created business entity or underlying workflow run. It never
returns prompt internals, hidden reasoning or unauthorized resource metadata.

### 6.2. Planning workflow APIs

Supporting endpoints retained for planning execution, focused proposal editing
and recovery:

```text
POST /api/v1/ai/planning-runs
GET  /api/v1/workflow-runs
GET  /api/v1/workflow-runs/{run_id}
POST /api/v1/workflow-runs/{run_id}/messages
GET  /api/v1/workflow-runs/{run_id}/events
PATCH /api/v1/proposals/{proposal_id}
POST /api/v1/approvals/{approval_id}/decision
```

`POST /api/v1/ai/planning-runs` accepts a typed initial message and locale,
commits the run/job/audit boundary and returns:

```http
202 Accepted
Location: /api/v1/workflow-runs/{run_id}
```

The workflow snapshot returns the current stage, run version, public timeline,
current proposal reference, validation summary and actions allowed for the
authenticated actor.

Posting a message resumes a human-input checkpoint or requests an AI revision.
It does not bypass the current workflow state or policy.

The conversation service is the normal public entry point. It delegates a
permitted planning turn to these existing contracts and links the resulting run
to the assistant turn. Direct planning-run endpoints remain authorized and
tested but are not exposed as a workflow picker in the UI.

Patching a proposal creates a new immutable version and queues validation. It
returns `202 Accepted`, the new `ETag` and the updated proposal reference.

The approval decision endpoint approves or rejects the exact proposal version
named by `If-Match`. Approval succeeds only after the business transaction
commits.

### 6.3. Manual planning APIs

The required manual CRUD families remain available regardless of provider state:

```text
/api/v1/goals
/api/v1/milestones
/api/v1/task-dependencies
/api/v1/acceptance-criteria
```

Goal has a separate typed API contract for versioning and audit even though it
does not have separate top-level navigation.

Authorized manual Manager mutations write directly after validation and audit.
They are not wrapped in AI proposal approval.

### 6.4. Mutation safety

Every retryable state-changing request has an `Idempotency-Key`. Update and
delete requests also require `If-Match`.

- `Idempotency-Key` prevents the same action from being applied twice after a
  double click, retry or lost response.
- `ETag` identifies the server resource version returned to a client.
- `If-Match` states which version the client intends to mutate.
- Reusing a key with the same normalized request returns the recorded response.
- Reusing a key with a different request returns `409 IDEMPOTENCY_KEY_REUSED`.
- Missing `If-Match` returns `428 PRECONDITION_REQUIRED`.
- A resource-version mismatch returns `412 RESOURCE_VERSION_MISMATCH`.
- A business-invariant violation returns `422 VALIDATION_FAILED`.

These rules extend the Phase 1 Project/Task conventions instead of introducing a
second concurrency contract.

For message submission, the idempotency scope includes actor, conversation and
key. Its fingerprint includes normalized message content, locale and any typed
client attachment references. Same-key/same-payload replay returns the original
message/turn; same-key/different-payload returns
`409 IDEMPOTENCY_KEY_REUSED`.

### 6.5. Error contract

Every product error uses the existing structured contract:

```json
{
  "error": {
    "code": "RESOURCE_VERSION_MISMATCH",
    "message_key": "common.error.resourceVersionMismatch",
    "request_id": "req_123",
    "details": {
      "current_version": 5
    }
  }
}
```

`code` drives stable frontend behavior, `message_key` drives Vietnamese/English
translation, `request_id` supports operational lookup and `details` contains only
safe structured information. Internal stack traces and raw provider errors are
never returned.

### 6.6. SSE contract

```http
GET /api/v1/ai/conversations/{conversation_id}/events
Accept: text/event-stream
Last-Event-ID: 12
```

SSE is a long-lived, server-to-browser HTTP response. The browser still sends
messages, edits and decisions through REST.

Rules:

- The server authorizes the conversation and rechecks current membership before
  streaming.
- Event `id` equals the persisted assistant-event sequence.
- Reconnect replays events after `Last-Event-ID`.
- Heartbeats allow dead connections to be detected.
- Only sanitized public payloads are streamed.
- Disconnecting does not cancel the worker or workflow.
- REST snapshot/polling remains the fallback.

The existing workflow-run event endpoint follows the same contract for focused
planning diagnostics. Frontend chat normally subscribes at conversation scope
so one stream survives intent changes across turns.

Native `EventSource` is sufficient for same-origin cookie authentication; Phase
2 does not add WebSocket infrastructure.

## 7. Minimum Agent Harness and planning graph

### 7.1. Harness components activated in Phase 2

| Harness component | Phase 2 responsibility |
| --- | --- |
| Turn Orchestrator | Own one user-message → assistant-response lifecycle |
| Intent Router | Select `work.read`, permitted `planning.create` or safe unavailable response |
| Capability Registry | Static, versioned Phase 2 capability descriptors and role/tool allowlists |
| Context Builder | Load the minimum permitted Project/Task/membership context |
| Policy Guard | Tenant, role, tool allowlist, risk and approval requirement |
| Planner/Executor | Run the bounded-agentic planning graph |
| Model Gateway | Provider-neutral typed model invocation |
| Verifier | Schema, completeness and deterministic business checks |
| Human Approval Gate | Pause, display diff, accept edit/reject/approve, resume |
| Checkpoint manager | Persist typed resumable state |
| Observability/eval | Versioned run metadata, traces, costs and golden cases |

The router is conversation-general but capability-bounded: it classifies every
turn without locking a conversation to one workflow, yet it can execute only
registered Phase 2 capabilities. Requests for assignment recommendation,
persisted daily updates, risk or reports receive an explicit
unsupported-capability result until their owning phase registers the capability.
No model-selected route can override deterministic capability or role policy.

### 7.2. Phase 2 turn routing

```text
persist user message + assistant turn
        ↓
resolve actor, organization and current permissions
        ↓
bounded intent classification
        ├── work.read + permitted
        │     → typed Project/Task read tools
        │     → evidence/freshness verifier
        │     → assistant answer card
        ├── planning.create + Admin/Manager
        │     → create/link Planning WorkflowRun
        │     → planning graph
        ├── known future capability
        │     → availability card, no fake execution
        └── forbidden/ambiguous
              → non-disclosing denial or one clarification question
```

Read tools query authoritative business services under actor/RLS context. The
model may phrase an answer from verified typed results but cannot invent missing
facts or broaden the query scope. Employee requests for planning mutation are
denied before a planning run or proposal is created.

### 7.3. Planning graph

```text
policy_and_scope_guard
        ↓
load_permitted_context
        ↓
planning_agent
        ├── missing information → await_manager_input → planning_agent
        ├── permitted context request → context builder → planning_agent
        ├── unsupported request → safe unsupported response
        └── enough information → generate_structured_plan
                                      ↓
                                validate_schema
                                  ├── invalid → one constrained repair
                                  └── still invalid → manual_fallback
                                      ↓
                              deterministic_verifier
                                  ├── repairable → one bounded revision
                                  ├── Manager action needed → DRAFT with errors
                                  └── valid → persist_proposal
                                      ↓
                              await_manager_decision
                                  ├── Reject → complete without business writes
                                  └── Approve → approval application service
```

The graph defines typed state, explicit nodes, conditional edges, retry limits,
stop conditions, checkpoints and fallback. The planning agent may choose content
and permitted branches; the policy guard and verifier remain deterministic.

### 7.4. Typed workflow state

Only structured execution/audit state is persisted:

```text
run_id, assistant_turn_id, organization_id, actor_membership_id, locale
current_stage, user_brief
context_reference_ids
understanding, assumptions, manager_answers
proposal_id, proposal_version
validation_result
retry_counters
workflow_version, prompt_version, schema_version
model_reference, verifier_version
```

No hidden chain-of-thought is requested or persisted. Conversation text and
model context remain temporary workflow information, not official business facts.

### 7.5. Context Builder

Each context reference records:

```text
source type and identifier
organization and permission basis
source version or deterministic fingerprint
timestamp and expiry when applicable
```

Only the current node's required context is loaded. Phase 2 reads structured
Project, Task and membership data; it does not add document retrieval, Qdrant,
RAG or GraphRAG.

Conversation history is selected turn-by-turn and bounded by relevance, role and
current resource permission. Losing access to a resource prevents it from being
loaded again even if an older message mentioned it.

### 7.6. Model Gateway

The project-owned contract is conceptually:

```text
StructuredModelRequest
→ ModelGateway.generate_structured(...)
→ StructuredModelResponse | normalized ModelGatewayError
```

Request/response contracts use project-owned Pydantic schemas. They do not expose
LangChain or provider-specific types to backend consumers.

The response contains:

- Parsed typed result.
- Provider/model reference.
- Prompt and schema version.
- Provider request reference when safe.
- Token usage when available.
- Latency and normalized finish metadata.

Normalized errors include timeout, unavailable, rate-limited and invalid-output
categories. OpenAI and mock adapters must satisfy the same contract tests.

### 7.7. Retry, budget and stop conditions

Default Phase 2 limits:

- One model invocation timeout is 60 seconds.
- Transient provider failure allows at most three total attempts with backoff.
- Invalid structured output allows one constrained repair request.
- A verifier-rejected plan allows at most one bounded AI revision.
- Human waiting time is excluded from active compute time.
- No node, tool or graph loop retries indefinitely.
- Proposal size, message length, token budget and active runtime have configured
  upper bounds.

Exhausted retries produce a safe error card and manual fallback, not an automatic
business write.

### 7.8. Future Skills boundary

The planning workflow is the first evaluated AI capability. Phase 2 does not
implement a general Skill Registry, but it preserves the long-term relation:

```text
Agent Harness → Workflow Graph → selected versioned Skill → typed Tool
              → backend application service
```

When an owning phase is authorized, a Skill declares its trigger, typed input and
output, required context, allowed tools, risk/approval policy, owner, semantic
version and evaluation cases. The model may suggest a Skill; deterministic
capability and permission policy decides whether it can run.

### 7.9. LangSmith

LangSmith traces run/node/model/verifier boundaries with workflow, prompt,
schema, model and verifier versions. It supports offline comparison of bilingual
golden cases.

- Trace upload is off by default in local and automated tests.
- Production tracing is explicitly configured and redacted.
- A LangSmith outage never fails the business workflow.
- LangSmith is not a business source of truth.
- Phase 2 does not add MLflow; overlapping experiment stores are unnecessary.

## 8. Authorization, RLS, audit and AI security

### 8.1. Authorization matrix

| Action | Admin/Manager | Employee | Model |
| --- | --- | --- | --- |
| View permitted planning data | Yes | Yes | Only through permitted context |
| Open Assistant/create conversation | Yes | Yes | No |
| Ask read-only Project/Task questions | Yes | Yes | Only through typed permitted tools |
| Manual planning CRUD | Yes | No | No |
| Start/edit AI proposal | Yes | No | Proposal generation only |
| Approve/reject | Yes | No | Never |
| Write business records | Through application services | No | Never directly |

Organization context is resolved from the authenticated membership. An arbitrary
organization identifier in a request, prompt, checkpoint or tool argument cannot
change it.

Every tool call and application service rechecks permission and tenant context.
The model cannot grant a user a role, select a tenant or bypass approval.

### 8.2. RLS and tenant isolation

- Every new tenant-owned table has non-null `organization_id`.
- Tenant-owned indexes, unique constraints and foreign keys include the tenant.
- PostgreSQL RLS is enabled and forced on every tenant-owned table.
- API and worker transactions establish tenant context explicitly.
- API and worker roles do not have `BYPASSRLS`.
- Cross-tenant identifiers are rejected by application validation and database
  constraints/RLS.
- Unauthorized lookup responses do not reveal whether another tenant's resource
  exists.

Each new resource requires negative API and direct PostgreSQL RLS tests.

Conversation, message, turn and assistant-event rows are tenant-owned and RLS
protected. Reading a transcript also rechecks actor membership and conversation
access. Historical answer text is not authority to reveal a resource after
permission is revoked; linked cards become unavailable or redacted when policy
requires it.

### 8.3. Audit evidence

Append-only audit covers:

- Conversation creation and rejected/forbidden Assistant mutation attempts.
- Turn routing metadata, capability selection and typed tool outcome references
  where required, without hidden reasoning.
- Manual planning create/update/delete and rejected attempts.
- Run start/failure and checkpoint transitions where required.
- AI-created and Manager-edited proposal versions.
- Validation outcomes.
- Approval attempt, conflict, approval, rejection and application.
- Successful creation of approved business records.

Audit records include actor, organization, action, resource, outcome, reason,
request/run/proposal/version references, timestamp and a safe diff/metadata set.
They exclude credentials, session tokens, hidden reasoning, raw provider errors
and unnecessary prompt content.

### 8.4. Prompt- and tool-injection defenses

User text and stored business text are always untrusted data, not higher-priority
instructions.

- Prompts separate trusted instructions, trusted structured context and untrusted
  content.
- Prior conversation messages are untrusted content and cannot redefine system,
  capability, tenant or role policy.
- Secrets and unauthorized data are never inserted into model context.
- Planning tools use typed schemas and a least-privilege allowlist.
- Tool arguments undergo entity resolution, tenant and permission validation.
- Model output cannot become SQL or a direct database mutation.
- Output passes schema validation and a deterministic verifier.
- Markdown/HTML is sanitized before rendering.
- High-risk/AI writes require human approval.
- Vietnamese and English injection fixtures cover direct, obfuscated and
  multi-turn attempts relevant to Phase 2.

Phase 2 has no document, email or web ingestion, which intentionally excludes the
larger indirect-injection surface until an integration phase is authorized.

### 8.5. Data handling and retention

- Structured business proposal, approval and audit records follow business
  retention rather than AI trace retention.
- Raw AI prompt/context retained for debugging expires within 30 days.
- Redacted traces expire within 90 days.
- Hidden chain-of-thought is not persisted.
- Production data is not automatically copied into training or evaluation.
- Evaluation examples are redacted, permission-safe, deduplicated and
  provenance-linked.
- Training, held-out evaluation and production feedback remain separate.

## 9. Frontend integration and fallback

### 9.1. Feature boundaries

```text
frontend planning feature
├── Project goal section
├── Milestone management
├── Dependency management
└── Acceptance Criteria management

frontend ai_proposals feature
├── reusable proposal/validation/approval cards
└── structured proposal editor

frontend ai_assistant feature
├── conversation list
├── chronological transcript and fixed composer
├── typed message/content-block renderer
├── read-only answer/evidence cards
├── inline planning progress and wizard cards
├── conversation-scoped SSE recovery
├── understanding/assumption/proposal cards
├── validation and diff
└── approval decision
```

TanStack Query owns server state and cache invalidation. Component state holds
only unsaved form input. Zod validates browser contracts, but backend schemas and
domain invariants remain authoritative.

SSE events trigger targeted refetch/invalidation. They do not directly replace
canonical Project, Proposal or Workflow objects in the cache.

All business UI strings use `next-intl` translation keys for Vietnamese and
English. The accessibility behavior approved in the UX spec applies to stepper,
cards, validation focus, dialogs, live regions and keyboard actions.

The Assistant page never derives a transcript by stacking the current planning
snapshot sections. It renders persisted messages in sequence. Planning status is
one typed content block associated with one turn; older turns and superseded
proposal cards remain visible and read-only.

### 9.2. Manual fallback paths

Manual planning works when:

- No OpenAI credential is configured.
- The provider is disabled, unavailable or times out.
- Structured output is malformed.
- The verifier rejects the result.
- Workflow retries are exhausted.
- LangSmith is unavailable.

There are two distinct provenance paths:

1. A Manager starts from the manual Project Plan UI and authors the content. The
   authorized mutation writes directly after validation/audit without approval.
2. A Manager chooses `Continue manually` from an AI run. Any validated AI-prefill
   remains an AI proposal with field provenance and still requires approval. Raw
   malformed output is never prefilled as fact. The Manager may discard the AI
   output and start a separate manual plan if a direct-write flow is desired.

This prevents an AI write from being relabeled as manual merely because the
provider failed after producing part of it.

## 10. Verification and evaluation strategy

### 10.1. Backend and database tests

- Conversation/message/turn atomic creation, sequence and idempotent replay.
- Assistant-event SSE ordering, authorization, reconnect and REST reconstruction.
- Role/capability routing and proof that Employee mutation requests create no
  planning run, proposal or business write.
- Typed Project/Task read-tool authorization, freshness and cross-tenant denial.
- Goal, Milestone, Dependency and Acceptance Criterion domain tests.
- Dependency cycle and date-invariant tests.
- Manual CRUD and role-authorization matrix.
- Negative cross-tenant API and PostgreSQL RLS tests for every new table.
- Idempotency replay/reuse and optimistic-concurrency tests.
- Proposal edit, stale, superseded approval and revalidation tests.
- Approval commit-once and rejection-no-side-effect tests.
- Audit and transactional-outbox tests.
- Worker claim, lease expiry, retry and crash-recovery tests.
- SSE ordering, authorization, reconnect and replay tests.
- Alembic upgrade, RLS policy and schema-drift checks.
- Public OpenAPI contract verification.

### 10.2. Workflow and model tests

The default suite uses the deterministic mock provider:

- Valid Vietnamese and English planning outputs.
- Missing information and human pause/resume.
- Malformed or incomplete structured output.
- Provider timeout, unavailable and bounded retry.
- Constrained repair success/failure.
- Deterministic verifier rejection.
- Unsupported future capability.
- Multi-turn intent switching inside one conversation.
- Employee read-only Q&A grounded only in permitted typed tool results.
- Prompt attempts to self-approve, escalate role or reference another tenant.
- Manual fallback after every essential model/verifier failure.
- Model Gateway contract parity between mock and hosted adapters.

Live OpenAI tests are separate, opt-in, network-dependent and credential-gated.
They do not run in the default automated suite.

### 10.3. Frontend and end-to-end tests

Component/contract tests cover:

- Conversation list, transcript order, fixed composer and multi-turn routing.
- Employee read-only answer/evidence cards and forbidden mutation response.
- Every workflow/card state.
- Proposal editing and version changes.
- Validation error, warning, stale, conflict and unavailable behavior.
- Disabled approval for incomplete/invalid/stale proposals.
- SSE disconnect and REST recovery.
- Vietnamese/English labels and locale dates.
- Keyboard, focus and accessible status announcements.

Primary E2E:

```text
Manager signs in
→ opens the universal AI Assistant and creates a conversation
→ enters a natural-language goal
→ confirms assumptions
→ receives a mock-provider proposal
→ edits a date and manually selects assignees
→ reviews deterministic validation and diff
→ approves
→ opens Project Plan/Task detail
→ sees Goal, Milestones, Tasks, Dependencies and Acceptance Criteria
```

Separate E2E scenarios cover Employee read-only Task Q&A, rejection and
provider-failure manual fallback.

### 10.4. Evaluation command and dataset

Phase 2 adds a stable repository-level command:

```text
make eval
```

The bilingual golden dataset evaluates typed behavior rather than exact prose:

- Structured-schema validity.
- Required-field coverage.
- Goal alignment with the brief.
- Milestone/Task decomposition coverage.
- Cycle-free, valid dependencies.
- Testable Acceptance Criteria.
- Explicit assumptions and unknowns.
- Unsupported-capability handling.
- Prompt-injection resistance at policy/tool boundaries.
- Correct fallback activation.

Each evaluation records workflow, prompt, schema, model/mock fixture and verifier
versions. A model or prompt change must pass the applicable golden suite before
becoming the default configuration.

## 11. Explicit non-goals

Phase 2 does not include:

- Employee skill profiles, capacity, workload or assignee recommendation.
- AI daily updates, blockers, deterministic risk or reports.
- Unrestricted general-purpose execution. The Phase 2 router is limited to
  permitted `work.read`, Admin/Manager `planning.create` and explicit
  unavailable-capability responses.
- Persistent small chat drawer/sidebar across product pages.
- Partial approval by Milestone or Task.
- Autonomous assignment, execution or replanning.
- Qdrant, RAG, GraphRAG or document ingestion.
- Google Calendar or other external side-effect integrations.
- Redis, Celery or a message broker.
- AI microservices or multi-agent swarms.
- Self-hosted inference, fine-tuning, distillation or MLflow.
- Kubernetes, Jenkins, GKE or a `deploy/` track.

## 12. Phase 2 Definition of Done interpretation

Phase 2 is complete only when all applicable Global Definition of Done gates and
the following Phase 2 outcomes pass:

- Manual Goal/Milestone/Dependency/Acceptance Criteria flows work without a
  model provider.
- Every authenticated role can use one full-page conversation-first Assistant;
  Employee read-only Q&A is permission-safe and cannot mutate work data.
- Conversation messages/turns are durable and reconstructable; one conversation
  can change intent across turns without exposing workflow selection.
- Planning runs execute asynchronously and can pause/resume safely.
- AI output is typed, editable, versioned and deterministically verified.
- No AI-proposed business record exists before Manager approval.
- Approval applies the exact current proposal once through application services,
  with audit and outbox records.
- Rejection creates no proposed business record.
- Invalid output, timeout and verifier rejection expose an editable safe fallback.
- Authorization and PostgreSQL RLS block cross-tenant access.
- Workflow, prompt, schema, model and verifier versions are recorded without
  hidden chain-of-thought.
- Bilingual golden evaluation and primary E2E pass with the mock provider.
- Formatting/lint, type checks, unit/integration tests, migration checks, eval and
  applicable E2E commands pass.
- No Phase 2 explicit non-goal was introduced.

Passing a happy-path demo alone does not complete the phase.

## 13. Reference material

- `AGENTS.md`
- `PLAN.md`, Phase 2 — AI Planning Proposal
- `AI_Native_Work_Management_System_Description.md`, Agent Harness, Context
  Engineering, Graph Engineering and Skills
- `docs/phase-2/UX_SPEC.md`
- LangGraph persistence and interrupts:
  <https://docs.langchain.com/oss/python/langgraph/persistence>
  and <https://docs.langchain.com/oss/python/langgraph/interrupts>
- LangChain structured output:
  <https://docs.langchain.com/oss/python/langchain/structured-output>
- LangSmith evaluation:
  <https://docs.langchain.com/langsmith/evaluation>
- OWASP LLM Prompt Injection Prevention Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html>
