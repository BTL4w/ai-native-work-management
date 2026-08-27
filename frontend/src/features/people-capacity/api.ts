import { requestJson, requestJsonWithMetadata } from "@/shared/api/client";

import {
  personSkillSchema,
  personSkillUpsertSchema,
  skillSchema,
  workOutcomeEvidenceSchema,
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
