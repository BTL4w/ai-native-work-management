import { requestJson, requestJsonWithMetadata } from "@/shared/api/client";

import {
  capacityEntrySchema,
  capacityUpsertSchema,
  leaveCreateSchema,
  leaveEntrySchema,
  leaveUpdateSchema,
  personSkillSchema,
  personSkillUpsertSchema,
  skillSchema,
  weeklyWorkloadSchema,
  workOutcomeEvidenceSchema,
  type CapacityUpsert,
  type LeaveCreate,
  type LeaveUpdate,
  type PersonSkillUpsert,
} from "./contracts";

const jsonHeaders = { "Content-Type": "application/json" };

export function listSkills() {
  return requestJson("/api/v1/skills", { schema: skillSchema.array() });
}

export function listPersonSkills(membershipId: string) {
  return requestJson(`/api/v1/members/${membershipId}/skills`, { schema: personSkillSchema.array() });
}

export function listWorkOutcomeEvidence(membershipId: string) {
  return requestJson(`/api/v1/members/${membershipId}/work-evidence`, { schema: workOutcomeEvidenceSchema.array() });
}

export function setPersonSkill(
  membershipId: string,
  skillId: string,
  input: PersonSkillUpsert,
  version: number | undefined,
  idempotencyKey: string,
) {
  const payload = personSkillUpsertSchema.parse(input);
  return requestJsonWithMetadata(`/api/v1/members/${membershipId}/skills/${skillId}`, {
    schema: personSkillSchema,
    init: {
      method: "PUT",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": idempotencyKey,
        ...(version === undefined ? {} : { "If-Match": `"${version}"` }),
      },
      body: JSON.stringify(payload),
    },
  });
}

export function deletePersonSkill(
  membershipId: string,
  skillId: string,
  version: number,
  idempotencyKey: string,
) {
  return requestJsonWithMetadata(`/api/v1/members/${membershipId}/skills/${skillId}`, {
    schema: personSkillSchema,
    init: {
      method: "DELETE",
      headers: {
        "Idempotency-Key": idempotencyKey,
        "If-Match": `"${version}"`,
      },
    },
  });
}

function withQuery(path: string, values: Record<string, string | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined) query.set(key, value);
  }
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export function listCapacity(membershipId?: string) {
  return requestJson(withQuery("/api/v1/capacity", { membership_id: membershipId }), {
    schema: capacityEntrySchema.array(),
  });
}

export function upsertCapacity(
  input: CapacityUpsert,
  version: number | undefined,
  idempotencyKey: string,
) {
  const payload = capacityUpsertSchema.parse(input);
  return requestJsonWithMetadata("/api/v1/capacity", {
    schema: capacityEntrySchema,
    init: {
      method: "POST",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": idempotencyKey,
        ...(version === undefined ? {} : { "If-Match": `"${version}"` }),
      },
      body: JSON.stringify(payload),
    },
  });
}

export function deleteCapacity(capacityId: string, version: number, idempotencyKey: string) {
  return requestJsonWithMetadata(`/api/v1/capacity/${capacityId}`, {
    schema: capacityEntrySchema,
    init: {
      method: "DELETE",
      headers: { "Idempotency-Key": idempotencyKey, "If-Match": `"${version}"` },
    },
  });
}

export function listLeave({ membershipId, startDate, endDate }: {
  membershipId?: string;
  startDate?: string;
  endDate?: string;
} = {}) {
  return requestJson(withQuery("/api/v1/leave", {
    membership_id: membershipId,
    start_date: startDate,
    end_date: endDate,
  }), { schema: leaveEntrySchema.array() });
}

export function createLeave(input: LeaveCreate, idempotencyKey: string) {
  const payload = leaveCreateSchema.parse(input);
  return requestJsonWithMetadata("/api/v1/leave", {
    schema: leaveEntrySchema,
    init: {
      method: "POST",
      headers: { ...jsonHeaders, "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(payload),
    },
  });
}

export function updateLeave(
  leaveId: string,
  input: LeaveUpdate,
  version: number,
  idempotencyKey: string,
) {
  const payload = leaveUpdateSchema.parse(input);
  return requestJsonWithMetadata(`/api/v1/leave/${leaveId}`, {
    schema: leaveEntrySchema,
    init: {
      method: "PATCH",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": idempotencyKey,
        "If-Match": `"${version}"`,
      },
      body: JSON.stringify(payload),
    },
  });
}

export function deleteLeave(leaveId: string, version: number, idempotencyKey: string) {
  return requestJsonWithMetadata(`/api/v1/leave/${leaveId}`, {
    schema: leaveEntrySchema,
    init: {
      method: "DELETE",
      headers: { "Idempotency-Key": idempotencyKey, "If-Match": `"${version}"` },
    },
  });
}

export function listWeeklyWorkload(weekStart: string, membershipId?: string) {
  return requestJson(withQuery("/api/v1/workload", {
    week_start: weekStart,
    membership_id: membershipId,
  }), { schema: weeklyWorkloadSchema.array() });
}
