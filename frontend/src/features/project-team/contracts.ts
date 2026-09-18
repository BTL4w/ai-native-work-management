import { z } from "zod";

const uuid = z.uuid();
const timestamp = z.iso.datetime();
const decimal = z.string().regex(/^\d+(?:\.\d+)?$/);

export const requirementItemInputSchema = z.object({
  skill_id: uuid,
  minimum_level: z.number().int().min(1).max(5),
  project_week_id: uuid,
  effort_hours: z.number().int().positive().max(2_147_483_647),
  source_task_ids: z.array(uuid),
}).strict();

export const teamRequirementSetSchema = z.object({
  id: uuid,
  organization_id: uuid,
  project_id: uuid,
  version: z.number().int().positive(),
  status: z.enum(["DRAFT", "CONFIRMED", "STALE"]),
  items: z.array(requirementItemInputSchema.extend({ id: uuid })),
  incomplete_items: z.array(z.object({ task_id: uuid, reason: z.string() }).strict()),
  created_at: timestamp,
  updated_at: timestamp,
}).strict();

export const reviseRequirementsSchema = z.object({
  action: z.literal("revise"),
  items: z.array(requirementItemInputSchema),
  incomplete_items: z.array(z.object({ task_id: uuid, reason: z.string() }).strict()),
}).strict().superRefine((value, context) => {
  const keys = value.items.map((item) => `${item.skill_id}:${item.project_week_id}`);
  if (new Set(keys).size !== keys.length) {
    context.addIssue({ code: "custom", path: ["items"], message: "Duplicate skill and week" });
  }
});

export const evidenceSchema = z.object({
  id: uuid,
  summary: z.string(),
  source_resource_type: z.string(),
  source_resource_id: uuid,
}).strict();

export const candidateRankingSchema = z.object({
  requirement_id: uuid,
  membership_id: uuid,
  display_name: z.string(),
  eligible: z.boolean(),
  hard_failure_codes: z.array(z.string()),
  skill_points: decimal,
  capacity_points: decimal,
  evidence_points: decimal,
  familiarity_points: decimal,
  total_points: decimal,
  effective_capacity_hours: z.number().int().nonnegative().nullable(),
  residual_capacity_hours: z.number().int().nonnegative().nullable(),
  evidence: z.array(evidenceSchema),
}).strict();

export const rankingPreviewSchema = z.object({
  requirement_set_id: uuid,
  requirement_version: z.number().int().positive(),
  policy_version: z.literal("ranking-v1"),
  origin: z.literal("DETERMINISTIC"),
  candidates: z.array(candidateRankingSchema),
  allocations: z.array(z.object({
    requirement_id: uuid,
    membership_id: uuid,
    allocated_effort_hours: decimal,
  }).strict()),
  uncovered: z.array(z.object({
    requirement_id: uuid,
    uncovered_effort_hours: decimal,
  }).strict()),
}).strict();

export const recommendationSelectionSchema = z.object({
  requirement_id: uuid,
  membership_id: uuid,
  allocated_effort_hours: decimal,
  warning_codes: z.array(z.string()),
  override_reason: z.string().nullable(),
}).strict();

const uncoveredRequirementSchema = z.object({
  requirement_id: uuid,
  uncovered_effort_hours: decimal,
}).strict();

const requirementDemandSchema = z.object({
  requirement_id: uuid,
  project_week_id: uuid,
  effort_hours: decimal,
}).strict();

const recommendationDiffSchema = z.object({
  added_membership_ids: z.array(uuid),
  removed_membership_ids: z.array(uuid),
  before: z.array(recommendationSelectionSchema),
  after: z.array(recommendationSelectionSchema),
}).strict();

export const recommendationVersionSchema = z.object({
  recommendation_id: uuid,
  version: z.number().int().positive(),
  requirement_set_id: uuid,
  requirement_version: z.number().int().positive(),
  policy_version: z.string().min(1),
  status: z.enum(["PROPOSED", "APPROVED", "REJECTED", "STALE"]),
  selections: z.array(recommendationSelectionSchema),
  alternatives: z.array(candidateRankingSchema),
  uncovered: z.array(uncoveredRequirementSchema),
  demands: z.array(requirementDemandSchema),
  diff: recommendationDiffSchema.nullable(),
  explanation_status: z.enum(["NOT_REQUESTED", "AVAILABLE", "UNAVAILABLE"]),
}).strict();

export const candidateOverrideInputSchema = z.object({
  requirement_id: uuid,
  selected_membership_id: uuid,
  override_reason: z.string().max(500).nullable(),
  allocated_effort_hours: decimal.nullable(),
}).strict();

export const reviseRecommendationSchema = z.object({
  overrides: z.array(candidateOverrideInputSchema),
}).strict();

export const projectTeamMembershipSchema = z.object({
  id: uuid,
  project_id: uuid,
  membership_id: uuid,
  decision_id: uuid,
  active: z.boolean(),
  created_at: timestamp,
}).strict();

export const projectTeamSchema = z.object({ memberships: z.array(projectTeamMembershipSchema) }).strict();

export const recommendationFeedbackSchema = z.object({
  id: uuid,
  recommendation_id: uuid,
  version: z.number().int().positive(),
  kind: z.enum(["accept", "override", "reject"]),
  comment: z.string(),
}).strict();

export type TeamRequirementSet = z.infer<typeof teamRequirementSetSchema>;
export type RequirementItemInput = z.infer<typeof requirementItemInputSchema>;
export type ReviseRequirements = z.infer<typeof reviseRequirementsSchema>;
export type RankingPreview = z.infer<typeof rankingPreviewSchema>;
export type CandidateRanking = z.infer<typeof candidateRankingSchema>;
export type RecommendationVersion = z.infer<typeof recommendationVersionSchema>;
export type CandidateOverrideInput = z.infer<typeof candidateOverrideInputSchema>;
export type ProjectTeam = z.infer<typeof projectTeamSchema>;
