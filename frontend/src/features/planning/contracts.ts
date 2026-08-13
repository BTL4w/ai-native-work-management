import { z } from "zod";

const versionFields = {
  version: z.number().int().positive(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
};

const nullableDescriptionSchema = z.string().max(5000).nullable();

export const goalCreateSchema = z.object({
  project_id: z.uuid(),
  title: z.string().trim().min(1).max(200),
  description: nullableDescriptionSchema.optional(),
  expected_outcomes: z.array(z.string()).default([]),
  target_date: z.iso.date().nullable().optional(),
});

export const goalUpdateSchema = z.object({
  title: z.string().trim().min(1).max(200).nullable().optional(),
  description: nullableDescriptionSchema.optional(),
  expected_outcomes: z.array(z.string()).nullable().optional(),
  target_date: z.iso.date().nullable().optional(),
});

export const goalSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  title: z.string(),
  description: z.string().nullable(),
  expected_outcomes: z.array(z.string()),
  target_date: z.iso.date().nullable(),
  ...versionFields,
});

export const milestoneCreateSchema = z.object({
  project_id: z.uuid(),
  name: z.string().trim().min(1).max(200),
  description: nullableDescriptionSchema.optional(),
  target_date: z.iso.date().nullable().optional(),
  position: z.number().int().positive(),
});

export const milestoneUpdateSchema = z.object({
  name: z.string().trim().min(1).max(200).nullable().optional(),
  description: nullableDescriptionSchema.optional(),
  target_date: z.iso.date().nullable().optional(),
  position: z.number().int().positive().nullable().optional(),
});

export const milestoneSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  name: z.string(),
  description: z.string().nullable(),
  target_date: z.iso.date().nullable(),
  position: z.number().int().positive(),
  ...versionFields,
});

export const projectWeekStatusSchema = z.enum(["PLANNED", "ACTIVE", "COMPLETED"]);
export const projectWeekCreateSchema = z.object({
  week_number: z.number().int().positive(),
  start_date: z.iso.date(),
  end_date: z.iso.date(),
  objective: z.string().trim().min(1).max(2000),
  status: projectWeekStatusSchema.default("PLANNED"),
});
export const projectWeekUpdateSchema = z.object({
  week_number: z.number().int().positive().nullable().optional(),
  start_date: z.iso.date().nullable().optional(),
  end_date: z.iso.date().nullable().optional(),
  objective: z.string().trim().min(1).max(2000).nullable().optional(),
  status: projectWeekStatusSchema.nullable().optional(),
});
export const projectWeekSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  week_number: z.number().int().positive(),
  start_date: z.iso.date(),
  end_date: z.iso.date(),
  objective: z.string(),
  status: projectWeekStatusSchema,
  ...versionFields,
});

export const dependencyCreateSchema = z.object({
  predecessor_task_id: z.uuid(),
  successor_task_id: z.uuid(),
});

export const dependencyUpdateSchema = z.object({
  predecessor_task_id: z.uuid().nullable().optional(),
  successor_task_id: z.uuid().nullable().optional(),
});

export const taskDependencySchema = z.object({
  id: z.uuid(),
  predecessor_task_id: z.uuid(),
  successor_task_id: z.uuid(),
  ...versionFields,
});

export const acceptanceCriterionCreateSchema = z.object({
  task_id: z.uuid(),
  text: z.string().trim().min(1).max(1000),
  position: z.number().int().positive(),
});

export const acceptanceCriterionUpdateSchema = z.object({
  text: z.string().trim().min(1).max(1000).nullable().optional(),
  position: z.number().int().positive().nullable().optional(),
});

export const acceptanceCriterionSchema = z.object({
  id: z.uuid(),
  task_id: z.uuid(),
  text: z.string(),
  position: z.number().int().positive(),
  ...versionFields,
});

export const deleteResultSchema = z.object({ id: z.uuid(), version: z.number().int().positive() });

function pageSchema<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    page: z.number().int().positive(),
    page_size: z.number().int().positive(),
    total: z.number().int().nonnegative(),
  });
}

export const goalPageSchema = pageSchema(goalSchema);
export const milestonePageSchema = pageSchema(milestoneSchema);
export const projectWeekPageSchema = pageSchema(projectWeekSchema);
export const dependencyPageSchema = pageSchema(taskDependencySchema);
export const acceptanceCriterionPageSchema = pageSchema(acceptanceCriterionSchema);
export const planningPageSchema = pageSchema(z.union([
  goalSchema,
  milestoneSchema,
  projectWeekSchema,
  taskDependencySchema,
  acceptanceCriterionSchema,
]));

export const projectPlanSchema = z.object({
  goal: goalSchema.nullable(),
  milestones: z.array(milestoneSchema),
  project_weeks: z.array(projectWeekSchema),
  dependencies: z.array(taskDependencySchema),
  acceptance_criteria: z.array(acceptanceCriterionSchema),
});

export type GoalInput = z.input<typeof goalCreateSchema>;
export type GoalPatch = z.input<typeof goalUpdateSchema>;
export type Goal = z.infer<typeof goalSchema>;
export type MilestoneInput = z.input<typeof milestoneCreateSchema>;
export type MilestonePatch = z.input<typeof milestoneUpdateSchema>;
export type Milestone = z.infer<typeof milestoneSchema>;
export type ProjectWeekInput = z.input<typeof projectWeekCreateSchema>;
export type ProjectWeekPatch = z.input<typeof projectWeekUpdateSchema>;
export type ProjectWeek = z.infer<typeof projectWeekSchema>;
export type DependencyInput = z.input<typeof dependencyCreateSchema>;
export type DependencyPatch = z.input<typeof dependencyUpdateSchema>;
export type TaskDependency = z.infer<typeof taskDependencySchema>;
export type AcceptanceCriterionInput = z.input<typeof acceptanceCriterionCreateSchema>;
export type AcceptanceCriterionPatch = z.input<typeof acceptanceCriterionUpdateSchema>;
export type AcceptanceCriterion = z.infer<typeof acceptanceCriterionSchema>;
export type ProjectPlan = z.infer<typeof projectPlanSchema>;
