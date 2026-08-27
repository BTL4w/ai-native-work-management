import { z } from "zod";

const uuid = z.uuid();
const timestamp = z.iso.datetime();

export const skillEvidenceTypeSchema = z.enum([
  "MANAGER_NOTE",
  "CERTIFICATE",
  "COMPLETED_TASK",
  "REVIEW_OUTCOME",
]);

export const skillSchema = z.object({
  id: uuid,
  organization_id: uuid,
  name: z.string(),
  normalized_name: z.string(),
  description: z.string().nullable(),
  active: z.boolean(),
  version: z.number().int().positive(),
  created_at: timestamp,
  updated_at: timestamp,
}).strict();

export const skillEvidenceSchema = z.object({
  id: uuid,
  organization_id: uuid,
  person_skill_id: uuid,
  evidence_type: skillEvidenceTypeSchema,
  summary: z.string(),
  source_resource_type: z.string(),
  source_resource_id: uuid,
  occurred_at: timestamp,
  created_by_membership_id: uuid,
  created_at: timestamp,
}).strict();

export const personSkillSchema = z.object({
  id: uuid,
  organization_id: uuid,
  membership_id: uuid,
  skill_id: uuid,
  level: z.number().int().min(1).max(5),
  verified_by_membership_id: uuid,
  verified_at: timestamp,
  version: z.number().int().positive(),
  created_at: timestamp,
  updated_at: timestamp,
  active: z.boolean(),
  evidence: z.array(skillEvidenceSchema),
}).strict();

export const workOutcomeEvidenceSchema = z.object({
  id: uuid,
  organization_id: uuid,
  membership_id: uuid,
  evidence_type: skillEvidenceTypeSchema,
  summary: z.string(),
  source_resource_type: z.string(),
  source_resource_id: uuid,
  source_resource_version: z.number().int().positive(),
  observed_at: timestamp,
  created_by_membership_id: uuid,
  created_at: timestamp,
}).strict();

export const personSkillUpsertSchema = z.object({
  skill_id: uuid,
  level: z.number().int().min(1).max(5),
  evidence: z.array(z.object({
    evidence_type: skillEvidenceTypeSchema,
    summary: z.string().trim().min(1).max(2000),
    source_resource_type: z.string().trim().min(1).max(100),
    source_resource_id: uuid,
    occurred_at: timestamp,
  }).strict()).max(20),
}).strict();

export type Skill = z.infer<typeof skillSchema>;
export type SkillEvidence = z.infer<typeof skillEvidenceSchema>;
export type PersonSkill = z.infer<typeof personSkillSchema>;
export type WorkOutcomeEvidence = z.infer<typeof workOutcomeEvidenceSchema>;
export type PersonSkillUpsert = z.infer<typeof personSkillUpsertSchema>;
