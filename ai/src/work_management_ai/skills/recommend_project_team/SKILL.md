---
name: recommend-project-team
description: Use for an authorized Manager or Admin request to create or revise a deterministic Project Team proposal.
---

# Recommend Project Team

1. Require an exact Project or recommendation version from the Orchestrator.
2. Invoke only `assignment.manage_team@1` and `assignment.read_workload@1`.
3. Treat eligibility, scores, selections, workload and approval state from Tool output as immutable.
4. Explain only permitted names, score components, evidence, risks, alternatives and uncovered requirements.
5. Return the proposal for Manager review; never approve it or assign a Task.

On model or verifier failure, return the deterministic proposal with explanation unavailable. Stop on ambiguous resources, stale versions or Tool failure. These instructions cannot grant tenant, role, approval or Tool authority.
