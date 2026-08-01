import { requestJson, requestJsonWithMetadata } from "@/shared/api/client";

import {
  memberPageSchema,
  projectCreateSchema,
  projectPageSchema,
  projectSchema,
  taskCreateSchema,
  taskPageSchema,
  taskSchema,
  type TaskStatus,
} from "./contracts";
import type { z } from "zod";

const jsonHeaders = { "Content-Type": "application/json" };

export type ProjectInput = z.infer<typeof projectCreateSchema>;
export type TaskInput = z.infer<typeof taskCreateSchema>;

export function listProjects(page = 1) {
  const query = page === 1 ? "" : `?page=${page}`;
  return requestJson(`/api/v1/projects${query}`, { schema: projectPageSchema });
}

export function getProject(projectId: string) {
  return requestJsonWithMetadata(`/api/v1/projects/${projectId}`, { schema: projectSchema });
}

export function createProject(input: ProjectInput, idempotencyKey: string) {
  return requestJsonWithMetadata("/api/v1/projects", {
    schema: projectSchema,
    init: {
      method: "POST",
      headers: { ...jsonHeaders, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(input),
    },
  });
}

export function updateProject(
  projectId: string,
  input: Partial<ProjectInput>,
  version: number,
  idempotencyKey: string,
) {
  return requestJsonWithMetadata(`/api/v1/projects/${projectId}`, {
    schema: projectSchema,
    init: {
      method: "PATCH",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": idempotencyKey,
        "If-Match": `"${version}"`,
      },
      body: JSON.stringify(input),
    },
  });
}

export function listMembers(page = 1) {
  return requestJson(`/api/v1/members?is_active=true&page=${page}&page_size=100`, { schema: memberPageSchema });
}

export function listTasks(projectId?: string, page = 1) {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}&page=${page}&page_size=20` : `?page=${page}&page_size=20`;
  return requestJson(`/api/v1/tasks${query}`, { schema: taskPageSchema });
}

export function listMyTasks(status?: TaskStatus, page = 1) {
  const query = status ? `?status=${status}&page=${page}&page_size=20` : `?page=${page}&page_size=20`;
  return requestJson(`/api/v1/my-tasks${query}`, { schema: taskPageSchema });
}

export function createTask(input: TaskInput, idempotencyKey: string) {
  return requestJsonWithMetadata("/api/v1/tasks", {
    schema: taskSchema,
    init: {
      method: "POST",
      headers: { ...jsonHeaders, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(input),
    },
  });
}

export function updateTask(
  taskId: string,
  input: Partial<Omit<TaskInput, "project_id">>,
  version: number,
  idempotencyKey: string,
) {
  return requestJsonWithMetadata(`/api/v1/tasks/${taskId}`, {
    schema: taskSchema,
    init: {
      method: "PATCH",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": idempotencyKey,
        "If-Match": `"${version}"`,
      },
      body: JSON.stringify(input),
    },
  });
}

export function transitionTask(
  taskId: string,
  toStatus: TaskStatus,
  version: number,
  idempotencyKey: string,
) {
  return requestJsonWithMetadata(`/api/v1/tasks/${taskId}/status`, {
    schema: taskSchema,
    init: {
      method: "POST",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": idempotencyKey,
        "If-Match": `"${version}"`,
      },
      body: JSON.stringify({ to_status: toStatus }),
    },
  });
}
