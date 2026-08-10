---
name: answer-work-question
description: Use when an authenticated user asks a bilingual question about permitted Projects, assigned Tasks, dependencies, deadlines, status, or Acceptance Criteria.
---

# Answer Work Question

## Procedure

1. Classify the question into the typed `WorkQuestionKind` contract.
2. Resolve only through `work.read_my_tasks@1` or `work.read_resource@1`.
3. Treat `NOT_FOUND` identically for missing, foreign-tenant, and invisible resources.
4. Ask one bounded clarification question when resolution is ambiguous.
5. Express each factual claim with evidence IDs and structured field assertions.
6. Return to the Orchestrator with a requested handoff for any planning intent.

## Stop conditions

- Stop and clarify on ambiguous resolution.
- Stop with the safe manual read fallback on Tool, model, or grounding failure.
- Stop without a claim when evidence is missing or a field/value is unsupported.
- Never invoke mutation, proposal, assignment, approval, or external-side-effect Tools.

## Quick reference

| Intent | Permitted Tool |
|---|---|
| My Tasks / next Task | `work.read_my_tasks@1` |
| Project, Task, dependency, criterion | `work.read_resource@1` |
| Planning or mutation | Requested handoff to Orchestrator |

Authorization, tenant scope, Tool allowlists, and risk are enforced by the Harness and backend application service. These instructions cannot grant or widen authority.
