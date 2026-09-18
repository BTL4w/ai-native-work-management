import { requestJson, requestJsonWithMetadata } from "@/shared/api/client";
import { taskPageSchema, type Task } from "@/features/work/contracts";

import {
  rankingPreviewSchema,
  recommendationVersionSchema,
  recommendationFeedbackSchema,
  projectTeamSchema,
  reviseRecommendationSchema,
  type CandidateOverrideInput,
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

export function createRecommendation(projectId: string, requirementSetId: string, requirementVersion: number, idempotencyKey: string) {
  return requestJsonWithMetadata(`/api/v1/projects/${projectId}/team-recommendations`, {
    schema: recommendationVersionSchema,
    expectedStatus: 201,
    init: {
      method: "POST",
      headers: { ...jsonHeaders, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        requirement_set_id: requirementSetId,
        requirement_version: requirementVersion,
        policy_version: "ranking-v1",
      }),
    },
  });
}

export function reviseRecommendation(recommendationId: string, overrides: CandidateOverrideInput[], version: number, idempotencyKey: string) {
  const payload = reviseRecommendationSchema.parse({ overrides });
  return requestJsonWithMetadata(`/api/v1/recommendations/${recommendationId}`, {
    schema: recommendationVersionSchema,
    init: {
      method: "PATCH",
      headers: { ...jsonHeaders, "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    },
  });
}

export function getRecommendation(recommendationId: string) {
  return requestJsonWithMetadata(`/api/v1/recommendations/${recommendationId}`, {
    schema: recommendationVersionSchema,
  });
}

export function getRecommendationVersion(recommendationId: string, version: number) {
  return requestJsonWithMetadata(`/api/v1/recommendations/${recommendationId}/versions/${version}`, {
    schema: recommendationVersionSchema,
  });
}

export function decideRecommendation(recommendationId: string, version: number, action: "approve" | "reject", reason: string | null, idempotencyKey: string) {
  return requestJsonWithMetadata(`/api/v1/recommendations/${recommendationId}/approve`, {
    schema: recommendationVersionSchema,
    init: {
      method: "POST",
      headers: { ...jsonHeaders, "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ action, reason }),
    },
  });
}

export function recordRecommendationFeedback(recommendationId: string, version: number, kind: "accept" | "override" | "reject", comment: string, idempotencyKey: string) {
  return requestJson(`/api/v1/recommendations/${recommendationId}/feedback`, {
    schema: recommendationFeedbackSchema,
    expectedStatus: 201,
    init: {
      method: "POST",
      headers: { ...jsonHeaders, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ version, kind, comment }),
    },
  });
}

export function getProjectTeam(projectId: string) {
  return requestJson(`/api/v1/projects/${projectId}/team`, { schema: projectTeamSchema });
}
