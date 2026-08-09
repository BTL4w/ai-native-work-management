# Conversation-First AI Assistant Corrective Design

## 1. Status and decision

This design supersedes the Phase 2 Task 9 assumption that a Planning Run is an
AI Assistant conversation. It preserves completed Tasks 1–8, including the
planning graph, immutable proposal lifecycle and atomic approval transaction.

The approved product contract is:

- `Trợ lý AI` is one full-page chat application available to every authenticated
  role.
- A user writes natural language without selecting a workflow.
- One Agent Harness routes each turn to a permitted bounded capability.
- Planning, assignment, daily update, risk and reporting are capabilities behind
  the Assistant, not separate chat products.
- Workflow names, graphs and job state are internal execution details.
- Manual product flows remain available without chat or a model provider.

This correction does not activate Phase 3, Phase 4, Phase 5 or Task 10 behavior.
Phase 2 implements only the shared shell, read-only Work Q&A over existing data
and Admin/Manager planning. Later phases register their capabilities into the
same shell.

## 2. Considered approaches

### A. Restyle the existing Planning Run page

Keep one run as one conversation and rearrange current sections to resemble a
chat transcript.

This is rejected. It cannot support multiple intents in one conversation,
Employee read-only questions or later daily-update/report turns without turning
the Planning Run aggregate into an unrelated general-purpose container.

### B. Conversation shell with bounded turn orchestration — selected

Create explicit Conversation, Message and Assistant Turn boundaries. Each turn
is routed to a registered capability and may optionally create a Workflow Run.
Planning remains the first durable workflow.

This adds the minimum durable foundation needed for the approved UX while
preserving phase discipline and existing workflow/approval safety.

### C. Multi-agent supervisor with specialist agents

Create a supervisor plus separate Planning, Daily Update, Risk and Reporting
agents immediately.

This is rejected for Core MVP. It expands orchestration, permissions, evaluation
and failure modes before benchmarks justify the complexity. The selected design
can add a specialist runtime later without changing the user-facing conversation
contract.

## 3. User experience

### 3.1. Page structure

```text
Application navigation | Conversation list | Active transcript
                                          ├── user messages
                                          ├── assistant prose
                                          ├── progress cards
                                          ├── evidence/answer cards
                                          ├── proposal/version/diff cards
                                          └── approval/error/availability cards
                                          ─────────────────────────────
                                          fixed composer
```

The transcript scrolls independently. The composer remains visible. The page
does not render a global four-step planning dashboard below the input.

Conversation history is chronological and durable. Superseded proposal cards
stay visible but become read-only and clearly identify the newer version.

### 3.2. Turn behavior

Every accepted user message creates exactly one Assistant Turn. The Assistant
may:

- answer from verified typed read results;
- ask one or more clarifying questions;
- append progress while a workflow runs;
- return one or more typed interactive cards;
- state that a capability is not available yet;
- deny an action without disclosing a foreign resource.

`Nhờ AI chỉnh` is a new user message. It creates a new turn and, for planning,
a new immutable proposal version with a visible diff. `Chỉnh tay` opens a focused
editor/drawer; saving creates the same immutable version boundary and returns a
new card to the transcript.

### 3.3. Role behavior

All authenticated roles can create and resume conversations.

Admin/Manager may:

- ask read-only questions over permitted work data;
- start and revise planning proposals;
- edit proposal fields manually;
- approve or reject when policy permits.

Employee may:

- ask about permitted Projects and assigned Tasks;
- ask what is in progress, due soon or next according to deterministic stored
  deadline/status facts;
- inspect permitted dependencies and Acceptance Criteria;
- retain existing Phase 1 permission to update an assigned Task status.

Employee may not edit Project Plan, Goal, Milestone, dependency, assignment,
proposal or approval. In Phase 4, Employee may edit and confirm their own
`Done / Blockers / Next steps` daily-update draft. That is user-owned progress
input, not permission to modify the plan.

## 4. Architecture

### 4.1. Runtime relationship

```text
Conversation
  → immutable User Message
  → Assistant Turn
      → Agent Harness
          → deterministic capability/role policy
          → bounded intent classification
          → Context Builder
          → selected capability
              ├── typed read tools → verified answer blocks
              ├── Planning WorkflowRun → proposal/approval blocks
              └── unavailable capability → availability block
  → immutable Assistant Message(s)
```

A Conversation is not a Workflow Run. An Assistant Turn may own zero or one
Workflow Run in Phase 2. Later designs may permit multiple explicitly bounded
child runs, but Phase 2 does not need that expansion.

### 4.2. Component boundaries

`backend/app/modules/assistant/` owns:

- conversation/message/turn application contracts;
- authorization, transaction and idempotency boundaries;
- PostgreSQL adapters and conversation event stream;
- typed Project/Task read ports;
- composition of the Agent Harness behind an application interface.

`ai/src/work_management_ai/orchestration/` owns:

- project-owned typed intent/capability contracts;
- bounded classifier and deterministic mock behavior;
- capability descriptors and routing output;
- no database adapters or direct business mutation.

`ai/workflows/planning/` remains the planning Workflow Graph. Existing Task 7
run/proposal/SSE APIs and Task 8 approval service remain focused downstream
contracts.

`frontend/src/features/ai-assistant/` owns:

- conversation list and active conversation query state;
- chronological transcript and fixed composer;
- typed content-block renderer;
- conversation-scoped SSE invalidation/recovery;
- role-aware suggestions and allowed actions.

`frontend/src/features/ai-proposals/` owns reusable proposal, validation,
approval and editor components. It is not the page-level Assistant controller.

## 5. Persistence model

The corrective slice requires a forward Alembic migration because the current
schema has Workflow Runs but no general conversation aggregate.

### 5.1. AssistantConversation

Tenant-owned container with:

```text
id, organization_id, created_by_membership_id
title, locale, status
last_message_sequence, version
created_at, updated_at
```

Conversation title is safe presentation metadata, not model memory or a business
fact.

### 5.2. AssistantMessage

Immutable ordered record with:

```text
id, organization_id, conversation_id, sequence
role: USER | ASSISTANT
content_blocks JSONB using a versioned project-owned schema
created_by_membership_id nullable for assistant output
assistant_turn_id nullable
created_at
```

The unique key includes organization, conversation and sequence. Public blocks
must not contain hidden reasoning, raw provider error, credentials or prompt
internals.

### 5.3. AssistantTurn

Durable execution record with:

```text
id, organization_id, conversation_id, user_message_id
status, intent, capability, risk_level
workflow_run_id nullable
router_version, model_reference nullable
error_code nullable
created_at, updated_at, completed_at nullable
```

One accepted user message has exactly one turn. A unique constraint makes this
the database-level idempotency backstop.

### 5.4. AssistantEvent

Append-only conversation-scoped event stream:

```text
id, organization_id, conversation_id, sequence
event_type, public_payload JSONB, occurred_at
```

SSE event IDs use this sequence. REST snapshots rebuild the canonical transcript.

All four tables use tenant-qualified foreign keys, indexes, forced RLS and the
existing non-`BYPASSRLS` runtime role.

## 6. API and event contracts

Primary Assistant API:

```text
POST /api/v1/ai/conversations
GET  /api/v1/ai/conversations
GET  /api/v1/ai/conversations/{conversation_id}
POST /api/v1/ai/conversations/{conversation_id}/messages
GET  /api/v1/ai/conversations/{conversation_id}/events
```

Posting a message requires `Idempotency-Key`. Its scope includes actor,
conversation and operation. The fingerprint includes normalized message,
locale and typed attachment references. Same key/payload returns the original
message and turn; different payload returns `409 IDEMPOTENCY_KEY_REUSED`.

The response is returned only after the user message, turn, initial event and
required job commit atomically. Planning routing links the turn to a run through
application services; routes never manipulate repositories directly.

Existing planning-run, proposal-edit, approval-decision and focused workflow SSE
contracts remain available. The Assistant UI no longer starts by treating the
workflow snapshot as its transcript.

## 7. Phase 2 capabilities

### 7.1. `work.read`

Available to every authenticated role. Typed read tools support only existing
Phase 1/2 facts needed for:

- assigned/current Tasks;
- next/due Tasks using deterministic status and deadline ordering;
- permitted Project and Task details;
- dependencies and Acceptance Criteria;
- unknown/stale/unavailable evidence states.

Tools resolve organization from the actor, enforce resource permissions and RLS,
return typed safe evidence and never mutate business data. The model may explain
verified results but cannot introduce unreturned facts.

`Task tiếp theo` is deterministic for the current schema: assigned
`IN_PROGRESS` Tasks first, then assigned `TO_DO` Tasks ordered by non-null due
date ascending, null due dates last, and stable `created_at`/ID tie-breakers.
Phase 2 does not invent a priority field that does not exist at HEAD.

### 7.2. `planning.create`

Available to Admin/Manager. The capability delegates to the existing Planning
Run service and graph. Missing-information questions, progress, proposal,
validation, diff and approval states are projected into Assistant messages and
cards. Approval still uses the completed atomic Task 8 service.

### 7.3. `capability.unavailable`

Recognizes known future intents, explains their owning phase and avoids simulated
success. It creates no workflow run or business row.

## 8. Later phase registration

Phase 3 registers assignment/workload recommendation capabilities. Results and
approval cards appear in the existing transcript.

Phase 4 registers daily-update, blocker and risk capabilities. Employee natural
language is extracted into a `Done / Blockers / Next steps` card. Nothing is
persisted until the Employee corrects or confirms it. Confirmed blockers become
evidence visible to permitted Managers. AI may notify or recommend; only an
authorized Manager/manual or approved proposal path changes the plan.

Phase 5 registers project-status and reporting capabilities. Exact numbers come
from deterministic queries/immutable snapshots; narratives may be model-drafted
and verified.

These phases do not create new Assistant tabs or force users to choose workflows.

## 9. Security, context and data handling

- Membership resolves organization for every conversation request, turn, job,
  tool call and event stream.
- Conversation history never grants access. Context Builder rechecks current
  permission and source freshness on every turn.
- Prior messages and stored business text are untrusted prompt input.
- Foreign or unauthorized resources use the existing non-disclosing contract.
- An Employee mutation request is denied before creating a Planning Run or
  Proposal and leaves required safe audit evidence.
- Typed content blocks are sanitized; raw model/provider errors and exception
  text are normalized before persistence or response.
- Raw AI context and redacted trace retention remain governed by the existing
  30/90-day boundaries. Business audit/proposal/approval retention is separate.
- AI cannot approve its own proposal or call database adapters directly.

## 10. Failure and recovery

- Conversation REST state is canonical; SSE only signals new persisted state.
- Disconnecting does not cancel an active turn or workflow.
- Reload reconstructs message order and current cards from PostgreSQL.
- A provider timeout appends a safe error/fallback block to the failed turn and
  leaves the composer usable where policy permits.
- A planning failure retains the manual planning fallback.
- Idempotent retry does not duplicate messages, turns, runs, proposals, approvals
  or business rows.
- Superseded/stale proposal cards are disabled and point to the current version.

## 11. Verification strategy

Backend and PostgreSQL tests cover:

- atomic conversation + user message + turn + event/job creation;
- message/event ordering and idempotent replay/reuse conflict;
- Admin/Manager/Employee capability matrix;
- negative cross-tenant API and direct RLS access;
- Employee read-only results and zero mutations;
- Employee planning/edit/approval denial before run/proposal creation;
- turn-to-planning-run linking and retry recovery;
- safe exception/provider normalization.

AI tests cover:

- bilingual bounded intent classification;
- deterministic mock routing;
- multi-turn intent changes in one conversation;
- tool-result grounding and unsupported future capability;
- prompt attempts to change tenant, role, capability or approval policy.

Frontend/E2E tests cover:

- conversation list, transcript order, fixed composer and reload recovery;
- inline progress/question/proposal/diff/approval/error cards;
- manual and AI-assisted proposal revision;
- Employee Task Q&A and forbidden mutations;
- Manager planning approval through the existing atomic transaction;
- provider failure and SSE reconnect with REST fallback;
- Vietnamese/English and accessibility behavior.

## 12. Explicit non-goals

- No Phase 3 assignee recommendation or capacity behavior.
- No Phase 4 daily-update persistence, blocker/risk calculation or notification.
- No Phase 5 report generation.
- No persistent chat drawer/sidebar on every page.
- No unrestricted autonomous agent, multi-agent swarm or agent-per-feature.
- No Redis, Celery, broker, Qdrant, RAG, Calendar or external side effect.
- No replacement or weakening of Task 8 approval, outbox, audit or stale checks.
- No Task 10 evaluation/security expansion or Task 11 closure in the corrective
  implementation slice.

## 13. Acceptance criteria

- Every authenticated role opens the same Assistant chat app.
- A conversation can contain multiple turns and change intent without selecting
  a workflow.
- Employee receives only permitted read-only Work facts and cannot edit plan or
  approval state.
- Manager planning appears as inline chronological cards, not a page-wide
  workflow dashboard.
- Manual edit and AI revision create immutable proposal versions and visible
  diffs.
- Approve/reject continues through the exact-version atomic Task 8 transaction.
- PostgreSQL is the source of truth for transcript reconstruction and all
  business state.
- Later phases can register new capabilities without replacing the Assistant UI
  or conversation aggregate.
