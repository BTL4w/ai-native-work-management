import { z } from "zod";

import { membershipRoleSchema } from "@/shared/api/contracts";

export const taskStatusSchema = z.enum(["TO_DO", "IN_PROGRESS", "DONE"]);

export const projectCreateSchema = z.object({
  name: z.string().min(1).max(160),
  description: z.string().max(5000).nullable().optional(),
});

export const projectUpdateSchema = z.object({
  name: z.string().min(1).max(160).nullable().optional(),
  description: z.string().max(5000).nullable().optional(),
});

export const taskCreateSchema = z.object({
  project_id: z.uuid(),
  milestone_id: z.uuid().nullable().optional(),
  title: z.string().min(1).max(200),
  description: z.string().max(10000).nullable().optional(),
  assignee_membership_id: z.uuid(),
  due_date: z.iso.date().nullable().optional(),
});

export const taskUpdateSchema = z.object({
  title: z.string().min(1).max(200).nullable().optional(),
  description: z.string().max(10000).nullable().optional(),
  assignee_membership_id: z.uuid().nullable().optional(),
  due_date: z.iso.date().nullable().optional(),
  milestone_id: z.uuid().nullable().optional(),
});
export const taskStatusRequestSchema = z.object({ to_status: taskStatusSchema });

export const projectSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  description: z.string().nullable(),
  version: z.number().int(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
});

export const projectPageSchema = z.object({
  items: z.array(projectSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
});

export const memberSchema = z.object({
  membership_id: z.uuid(),
  display_name: z.string(),
  role: membershipRoleSchema,
  is_active: z.boolean(),
});

export const memberPageSchema = z.object({
  items: z.array(memberSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
});

export const assigneeSchema = z.object({
  membership_id: z.uuid(),
  display_name: z.string(),
});

export const taskSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  milestone_id: z.uuid().nullable(),
  title: z.string(),
  description: z.string().nullable(),
  assignee: assigneeSchema,
  status: taskStatusSchema,
  due_date: z.iso.date().nullable(),
  version: z.number().int(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
});

export const taskPageSchema = z.object({
  items: z.array(taskSchema),
  page: z.number().int(),
  page_size: z.number().int(),
  total: z.number().int(),
});

export type Project = z.infer<typeof projectSchema>;
export type Member = z.infer<typeof memberSchema>;
export type Task = z.infer<typeof taskSchema>;
export type TaskStatus = z.infer<typeof taskStatusSchema>;
export type ProjectPage = z.infer<typeof projectPageSchema>;
export type MemberPage = z.infer<typeof memberPageSchema>;
export type TaskPage = z.infer<typeof taskPageSchema>;
