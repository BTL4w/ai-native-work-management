---
name: revise-project-plan
description: Use when an authorized Manager or Admin requests changes to one exact immutable Planning proposal version.
---

# Revise Project Plan

## Procedure

1. Require workflow, proposal, exact base version, and Manager instruction.
2. Generate against only that immutable base and permission-filtered context.
3. Preserve unique stable Task refs and existing Manager-selected assignees.
4. Clear assignees on newly introduced Tasks and run deterministic verification.
5. Return the draft through `planning.manage_run@1` for backend freshness checks and append.
6. Stop at Manager review; never persist directly, approve, or apply business rows.

Duplicate or missing refs, stale versions, invalid structure, or verifier failures use the manual-editable fallback.
