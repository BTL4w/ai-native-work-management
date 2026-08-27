import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import { listPersonSkills, listSkills, setPersonSkill } from "./api";

const organizationId = "11111111-1111-4111-8111-111111111111";
const membershipId = "22222222-2222-4222-8222-222222222222";
const skillId = "33333333-3333-4333-8333-333333333333";
const personSkillId = "44444444-4444-4444-8444-444444444444";
const timestamp = "2026-08-24T10:00:00Z";

const skill = {
  id: skillId, organization_id: organizationId, name: "Product design", normalized_name: "product design",
  description: null, active: true, version: 1, created_at: timestamp, updated_at: timestamp,
};
const personSkill = {
  id: personSkillId, organization_id: organizationId, membership_id: membershipId, skill_id: skillId,
  level: 5, verified_by_membership_id: membershipId, verified_at: timestamp, version: 2,
  created_at: timestamp, updated_at: timestamp, active: true, evidence: [],
};
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", ...headers },
});

describe("people-capacity API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the Task 3 endpoints with strict response parsing", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/skills") return response([skill]);
      if (String(input) === `/api/v1/members/${membershipId}/skills`) return response([personSkill]);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(listSkills()).resolves.toEqual([skill]);
    await expect(listPersonSkills(membershipId)).resolves.toEqual([personSkill]);
  });

  it("sends caller-owned idempotency and an exact ETag when revising a verified skill", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(personSkill, 200, { ETag: '"2"' }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(setPersonSkill(membershipId, skillId, {
      skill_id: skillId,
      level: 5,
      evidence: [],
    }, 2, "person-skill-save-key")).resolves.toEqual({ data: personSkill, etag: '"2"', replayed: false });

    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/members/${membershipId}/skills/${skillId}`, expect.objectContaining({
      method: "PUT",
      headers: expect.objectContaining({
        "Idempotency-Key": "person-skill-save-key",
        "If-Match": '"2"',
      }),
    }));
  });

  it("rejects a successful response with extra fields", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([{ ...skill, hidden_trace: "secret" }])));

    const error = await listSkills().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
