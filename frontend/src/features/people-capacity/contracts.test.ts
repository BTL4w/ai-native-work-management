import { describe, expect, it } from "vitest";

import {
  personSkillSchema,
  skillSchema,
  workOutcomeEvidenceSchema,
} from "./contracts";

const organizationId = "11111111-1111-4111-8111-111111111111";
const membershipId = "22222222-2222-4222-8222-222222222222";
const skillId = "33333333-3333-4333-8333-333333333333";
const personSkillId = "44444444-4444-4444-8444-444444444444";
const evidenceId = "55555555-5555-4555-8555-555555555555";
const timestamp = "2026-08-24T10:00:00Z";

const skill = {
  id: skillId,
  organization_id: organizationId,
  name: "Product design",
  normalized_name: "product design",
  description: "Turns customer needs into usable interfaces.",
  active: true,
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
};

const personSkill = {
  id: personSkillId,
  organization_id: organizationId,
  membership_id: membershipId,
  skill_id: skillId,
  level: 5,
  verified_by_membership_id: membershipId,
  verified_at: timestamp,
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
  active: true,
  evidence: [{
    id: evidenceId,
    organization_id: organizationId,
    person_skill_id: personSkillId,
    evidence_type: "MANAGER_NOTE",
    summary: "Delivered launch UI",
    source_resource_type: "manager_note",
    source_resource_id: membershipId,
    occurred_at: timestamp,
    created_by_membership_id: membershipId,
    created_at: timestamp,
  }],
};

describe("people-capacity contracts", () => {
  it("parses Task 3 skill and verified-person-skill responses", () => {
    expect(skillSchema.parse(skill)).toEqual(skill);
    expect(personSkillSchema.parse(personSkill)).toEqual(personSkill);
  });

  it("rejects malformed or extra API response fields", () => {
    expect(skillSchema.safeParse({ ...skill, unsafe_provider_trace: "do not render" }).success).toBe(false);
    expect(personSkillSchema.safeParse({ ...personSkill, level: 6 }).success).toBe(false);
  });

  it("requires versioned provenance for work-outcome evidence without a global score", () => {
    const workEvidence = {
      id: evidenceId,
      organization_id: organizationId,
      membership_id: membershipId,
      evidence_type: "COMPLETED_TASK",
      summary: "Completed customer launch task",
      source_resource_type: "task",
      source_resource_id: skillId,
      source_resource_version: 3,
      observed_at: timestamp,
      created_by_membership_id: membershipId,
      created_at: timestamp,
    };

    expect(workOutcomeEvidenceSchema.safeParse(workEvidence).success).toBe(true);
    expect(workOutcomeEvidenceSchema.safeParse({ ...workEvidence, source_resource_version: 0 }).success).toBe(false);
    expect(workOutcomeEvidenceSchema.safeParse({ ...workEvidence, score: 98 }).success).toBe(false);
  });
});
