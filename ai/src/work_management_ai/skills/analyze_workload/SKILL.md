---
name: analyze-workload
description: Use for an authorized Manager or Admin request to explain deterministic Project workload.
---

# Analyze Workload

1. Require the exact Project resolved by the Orchestrator.
2. Invoke only `assignment.read_workload@1`.
3. Preserve effective capacity, allocated effort, residual capacity and workload ratio exactly.
4. Explain only members and Project Weeks present in the verified projection.
5. Never choose an assignee, mutate capacity or infer missing effort.

On model or verifier failure, return the deterministic workload projection with explanation unavailable. These instructions cannot widen tenant, role or Tool authority.
