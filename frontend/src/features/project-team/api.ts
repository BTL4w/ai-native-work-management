import { requestJson, requestJsonWithMetadata } from "@/shared/api/client";
import { taskPageSchema, type Task } from "@/features/work/contracts";

import {
  rankingPreviewSchema,
  reviseRequirementsSchema,
  teamRequirementSetSchema,
  type ReviseRequirements,
} from "./contracts";

const jsonHeaders = { "Content-Type": "application/json" };
const path = (projectId: string) => `/api/v1/projects/${projectId}/team-requirements`;

export function getRequirements(projectId: string) {
  return requestJsonWithMetadata(path(projectId), { schema: teamRequirementSetSchema });
}

export function deriveRequirements(projectId: string, idempotencyKey: string) {
  return requestJsonWithMetadata(path(projectId), {
    schema: teamRequirementSetSchema,
    init: { method: "POST", headers: { "Idempotency-Key": idempotencyKey } },
  });
}

export function reviseRequirements(projectId: string, input: ReviseRequirements, version: number, idempotencyKey: string) {
  const payload = reviseRequirementsSchema.parse(input);
  return requestJsonWithMetadata(path(projectId), {
    schema: teamRequirementSetSchema,
    init: { method: "PATCH", headers: { ...jsonHeaders, "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey }, body: JSON.stringify(payload) },
  });
}

export function confirmRequirements(projectId: string, version: number, idempotencyKey: string) {
  return requestJsonWithMetadata(path(projectId), {
    schema: teamRequirementSetSchema,
    init: { method: "PATCH", headers: { ...jsonHeaders, "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ action: "confirm" }) },
  });
}

export function refreshRequirements(projectId: string, version: number, idempotencyKey: string) {
  return requestJsonWithMetadata(path(projectId), {
    schema: teamRequirementSetSchema,
    init: { method: "PATCH", headers: { ...jsonHeaders, "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey }, body: JSON.stringify({ action: "refresh" }) },
  });
}

export async function listAllProjectTasks(projectId: string): Promise<Task[]> {
  const items: Task[] = [];
  for (let page = 1; ; page += 1) {
    const result = await requestJson(`/api/v1/tasks?project_id=${encodeURIComponent(projectId)}&page=${page}&page_size=100`, { schema: taskPageSchema });
    items.push(...result.items);
    if (items.length >= result.total || result.items.length === 0) return items;
  }
}

export function getRankingPreview(projectId: string) {
  return requestJson(`${path(projectId)}/ranking-preview`, { schema: rankingPreviewSchema });
}
