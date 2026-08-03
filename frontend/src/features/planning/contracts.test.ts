import { describe, expect, it } from "vitest";

import {
  acceptanceCriterionCreateSchema,
  acceptanceCriterionSchema,
  goalSchema,
  projectPlanSchema,
} from "./contracts";

const uuid = "11111111-1111-4111-8111-111111111111";
const timestamp = "2026-08-02T10:00:00Z";

const goal = {
  id: uuid,
  project_id: uuid,
  title: "Launch the service",
  description: null,
  expected_outcomes: ["First customer onboarded"],
  target_date: "2026-09-01",
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
};

const criterion = {
  id: uuid,
  task_id: uuid,
  text: "Customs form accepted",
  position: 1,
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
};

describe("planning contracts", () => {
  it("parses a project plan response", () => {
    expect(projectPlanSchema.parse({
      goal: null,
      milestones: [],
      dependencies: [],
      acceptance_criteria: [],
    })).toEqual({
      goal: null,
      milestones: [],
      dependencies: [],
      acceptance_criteria: [],
    });
  });

  it("rejects invalid UUIDs in planning resources", () => {
    expect(goalSchema.safeParse({ ...goal, project_id: "not-a-uuid" }).success).toBe(false);
  });

  it("rejects an empty normalized acceptance criterion", () => {
    expect(acceptanceCriterionCreateSchema.safeParse({
      task_id: uuid,
      text: "   ",
      position: 1,
    }).success).toBe(false);
  });

  it("rejects planning responses without a resource version", () => {
    const missingVersion: Partial<typeof criterion> = { ...criterion };
    delete missingVersion.version;
    expect(acceptanceCriterionSchema.safeParse(missingVersion).success).toBe(false);
  });
});
