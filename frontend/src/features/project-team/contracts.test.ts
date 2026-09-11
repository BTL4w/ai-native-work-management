import { describe, expect, it } from "vitest";

import {
  rankingPreviewSchema,
  teamRequirementSetSchema,
  reviseRequirementsSchema,
} from "./contracts";

const id = (suffix: string) => `00000000-0000-4000-8000-${suffix.padStart(12, "0")}`;

describe("project team contracts", () => {
  it("accepts a strict requirement snapshot", () => {
    expect(teamRequirementSetSchema.parse({
      id: id("1"), organization_id: id("2"), project_id: id("3"), version: 2,
      status: "DRAFT", items: [{ id: id("4"), skill_id: id("5"), minimum_level: 3,
        project_week_id: id("6"), effort_hours: 8, source_task_ids: [id("7")] }],
      incomplete_items: [], created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z",
    }).version).toBe(2);
  });

  it("rejects duplicate skill/week rows before a revision request", () => {
    const item = { skill_id: id("5"), minimum_level: 3, project_week_id: id("6"), effort_hours: 8, source_task_ids: [] };
    expect(reviseRequirementsSchema.safeParse({ action: "revise", items: [item, item], incomplete_items: [] }).success).toBe(false);
  });

  it("keeps ranking scores numeric strings and capacity unknown explicit", () => {
    const value = rankingPreviewSchema.parse({
      requirement_set_id: id("1"), requirement_version: 2, policy_version: "ranking-v1",
      origin: "DETERMINISTIC", candidates: [{ requirement_id: id("4"), membership_id: id("8"),
        display_name: "Lan", eligible: false, hard_failure_codes: ["WEEKLY_WORKLOAD_MISSING"],
        skill_points: "0.0000", capacity_points: "0.0000", evidence_points: "0.0000",
        familiarity_points: "0.0000", total_points: "0.0000", effective_capacity_hours: null,
        residual_capacity_hours: null, evidence: [] }], allocations: [],
      uncovered: [{ requirement_id: id("4"), uncovered_effort_hours: "8" }],
    });
    expect(value.candidates[0].residual_capacity_hours).toBeNull();
  });
});
