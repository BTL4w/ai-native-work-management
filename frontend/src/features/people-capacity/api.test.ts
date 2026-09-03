import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import {
  createLeave,
  listCapacity,
  listLeave,
  listPersonSkills,
  listSkills,
  listWeeklyWorkload,
  setPersonSkill,
  updateLeave,
  upsertCapacity,
} from "./api";

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

  it("queries availability and derived workload for an exact week", async () => {
    const capacity = {
      id: personSkillId, organization_id: organizationId, membership_id: membershipId,
      kind: "DEFAULT", hours: 40, effective_from: "2000-01-01", effective_to: "2099-12-31",
      week_start: null, version: 1, created_at: timestamp, updated_at: timestamp,
    };
    const leave = {
      id: skillId, organization_id: organizationId, membership_id: membershipId,
      start_date: "2026-08-24", end_date: "2026-08-24", unavailable_hours: 8,
      version: 1, created_at: timestamp, updated_at: timestamp,
    };
    const workload = {
      membership_id: membershipId, project_week_id: skillId, effective_capacity_hours: 32,
      allocated_effort_hours: 24, residual_capacity_hours: 8, workload_ratio: "0.75",
    };
    const requested: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      requested.push(path);
      if (path === `/api/v1/capacity?membership_id=${membershipId}`) return response([capacity]);
      if (path === `/api/v1/leave?membership_id=${membershipId}&start_date=2026-08-24&end_date=2026-08-30`) return response([leave]);
      if (path === `/api/v1/workload?week_start=2026-08-24&membership_id=${membershipId}`) return response([workload]);
      throw new Error(`Unexpected request: ${path}`);
    }));

    await expect(listCapacity(membershipId)).resolves.toEqual([capacity]);
    await expect(listLeave({ membershipId, startDate: "2026-08-24", endDate: "2026-08-30" })).resolves.toEqual([leave]);
    await expect(listWeeklyWorkload("2026-08-24", membershipId)).resolves.toEqual([workload]);
    expect(requested).toHaveLength(3);
  });

  it("sends idempotency and exact versions for availability mutations", async () => {
    const capacity = {
      id: personSkillId, organization_id: organizationId, membership_id: membershipId,
      kind: "OVERRIDE", hours: 32, effective_from: "2026-08-24", effective_to: "2026-08-30",
      week_start: "2026-08-24", version: 2, created_at: timestamp, updated_at: timestamp,
    };
    const leave = {
      id: skillId, organization_id: organizationId, membership_id: membershipId,
      start_date: "2026-08-24", end_date: "2026-08-24", unavailable_hours: 8,
      version: 2, created_at: timestamp, updated_at: timestamp,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(capacity, 200, { ETag: '"2"' }))
      .mockResolvedValueOnce(response(leave, 201, { ETag: '"1"' }))
      .mockResolvedValueOnce(response(leave, 200, { ETag: '"2"' }));
    vi.stubGlobal("fetch", fetchMock);

    await upsertCapacity({ membership_id: membershipId, kind: "OVERRIDE", week_start: "2026-08-24", hours: 32 }, 1, "capacity-save-key");
    await createLeave({ membership_id: membershipId, start_date: "2026-08-24", end_date: "2026-08-24", unavailable_hours: 8 }, "leave-create-key");
    await updateLeave(skillId, { unavailable_hours: 8 }, 1, "leave-update-key");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/capacity", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ "Idempotency-Key": "capacity-save-key", "If-Match": '"1"' }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/v1/leave", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ "Idempotency-Key": "leave-create-key" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, `/api/v1/leave/${skillId}`, expect.objectContaining({
      method: "PATCH", headers: expect.objectContaining({ "Idempotency-Key": "leave-update-key", "If-Match": '"1"' }),
    }));
  });
});
