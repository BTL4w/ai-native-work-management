import { z } from "zod";

const uuid = z.uuid();
const timestamp = z.iso.datetime();
const date = z.iso.date();
const hours = z.number().int().min(0).max(168);

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

export const capacityKindSchema = z.enum(["DEFAULT", "OVERRIDE"]);

export const capacityEntrySchema = z.object({
  id: uuid,
  organization_id: uuid,
  membership_id: uuid,
  kind: capacityKindSchema,
  hours,
  effective_from: date,
  effective_to: date,
  week_start: date.nullable(),
  version: z.number().int().positive(),
  created_at: timestamp,
  updated_at: timestamp,
}).strict();

export const capacityUpsertSchema = z.object({
  membership_id: uuid,
  kind: capacityKindSchema,
  week_start: date.nullish(),
  hours,
  effective_from: date.nullish(),
  effective_to: date.nullish(),
}).strict().superRefine((value, context) => {
  if (value.kind === "DEFAULT" && value.week_start != null) {
    context.addIssue({ code: "custom", path: ["week_start"], message: "Default capacity cannot target a week" });
  }
  if (value.kind === "OVERRIDE" && value.week_start == null) {
    context.addIssue({ code: "custom", path: ["week_start"], message: "Override capacity requires a week" });
  }
});

export const leaveEntrySchema = z.object({
  id: uuid,
  organization_id: uuid,
  membership_id: uuid,
  start_date: date,
  end_date: date,
  unavailable_hours: hours,
  version: z.number().int().positive(),
  created_at: timestamp,
  updated_at: timestamp,
}).strict();

export const leaveCreateSchema = z.object({
  membership_id: uuid,
  start_date: date,
  end_date: date,
  unavailable_hours: hours,
}).strict();

export const leaveUpdateSchema = z.object({
  start_date: date.nullish(),
  end_date: date.nullish(),
  unavailable_hours: hours.nullish(),
}).strict();

export const weeklyWorkloadSchema = z.object({
  membership_id: uuid,
  project_week_id: uuid,
  effective_capacity_hours: z.number().int().nonnegative(),
  allocated_effort_hours: z.number().int().nonnegative(),
  residual_capacity_hours: z.number().int().nonnegative(),
  workload_ratio: z.string().regex(/^\d+(?:\.\d+)?$/).nullable(),
}).strict();

export type Skill = z.infer<typeof skillSchema>;
export type SkillEvidence = z.infer<typeof skillEvidenceSchema>;
export type PersonSkill = z.infer<typeof personSkillSchema>;
export type WorkOutcomeEvidence = z.infer<typeof workOutcomeEvidenceSchema>;
export type PersonSkillUpsert = z.infer<typeof personSkillUpsertSchema>;
export type CapacityKind = z.infer<typeof capacityKindSchema>;
export type CapacityEntry = z.infer<typeof capacityEntrySchema>;
export type CapacityUpsert = z.infer<typeof capacityUpsertSchema>;
export type LeaveEntry = z.infer<typeof leaveEntrySchema>;
export type LeaveCreate = z.infer<typeof leaveCreateSchema>;
export type LeaveUpdate = z.infer<typeof leaveUpdateSchema>;
export type WeeklyWorkload = z.infer<typeof weeklyWorkloadSchema>;
