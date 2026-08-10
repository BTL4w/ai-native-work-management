---
name: create-project-plan
description: Use when an authorized Manager or Admin asks to create, resume, or explain a Project planning proposal.
---

# Create Project Plan

## Procedure

1. Use only permission-filtered context and the typed Planning input.
2. Call only `planning.manage_run@1` with `CREATE`, `RESUME_INPUT`, or `EXPLAIN`.
3. Return Manager questions or an immutable proposal reference.
4. Stop at `MANAGER_DECISION`; never approve or apply the proposal.

## Boundaries

- Keep stable Project, Milestone, Task, dependency, and criterion references.
- Never accept tenant, role, approval, decision, or created-business-ID fields.
- Assignment requests return to the Orchestrator as a requested handoff.
- Model, Tool, or verifier failure returns the manual-editable fallback.

Authorization and approval state come only from the Harness and backend service.
