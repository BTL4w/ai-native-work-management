import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import {
  createGoal,
  deleteAcceptanceCriterion,
  getProjectPlan,
  updateMilestone,
} from "./api";

const projectId = "11111111-1111-4111-8111-111111111111";
const resourceId = "22222222-2222-4222-8222-222222222222";
const timestamp = "2026-08-02T10:00:00Z";
const page = (items: unknown[]) => ({ items, page: 1, page_size: 100, total: items.length });
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

const goal = {
  id: resourceId,
  project_id: projectId,
  title: "Launch",
  description: null,
  expected_outcomes: [],
  target_date: null,
  version: 1,
  created_at: timestamp,
  updated_at: timestamp,
};

const milestone = {
  id: resourceId,
  project_id: projectId,
  name: "Pilot",
  description: null,
  target_date: null,
  position: 1,
  version: 2,
  created_at: timestamp,
  updated_at: timestamp,
};

describe("planning API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("loads the project-scoped manual plan", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === `/api/v1/goals?project_id=${projectId}&page=1&page_size=100`) return response(page([goal]));
      if (path === `/api/v1/milestones?project_id=${projectId}&page=1&page_size=100`) return response(page([]));
      if (path === `/api/v1/task-dependencies?project_id=${projectId}&page=1&page_size=100`) return response(page([]));
      if (path === `/api/v1/tasks?project_id=${projectId}&page=1&page_size=100`) return response(page([]));
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getProjectPlan(projectId)).resolves.toEqual({
      goal,
      milestones: [],
      dependencies: [],
      acceptance_criteria: [],
    });
  });

  it("creates a Goal with caller-owned idempotency and returns metadata", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(goal, 201, { ETag: '"1"' }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createGoal({
      project_id: projectId,
      title: "Launch",
      description: null,
      expected_outcomes: [],
      target_date: null,
    }, "goal-submit-key-1234")).resolves.toEqual({ data: goal, etag: '"1"', replayed: false });
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/goals", expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "goal-submit-key-1234" }),
    }));
  });

  it("updates a Milestone with optimistic concurrency", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(milestone));
    vi.stubGlobal("fetch", fetchMock);

    await updateMilestone(resourceId, { name: "Pilot" }, 2, "milestone-key-1234");

    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/milestones/${resourceId}`, expect.objectContaining({
      method: "PATCH",
      headers: expect.objectContaining({
        "Idempotency-Key": "milestone-key-1234",
        "If-Match": '"2"',
      }),
    }));
  });

  it("deletes an Acceptance Criterion with version and idempotency headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ id: resourceId, version: 3 }));
    vi.stubGlobal("fetch", fetchMock);

    await deleteAcceptanceCriterion(resourceId, 2, "criterion-key-1234");

    expect(fetchMock).toHaveBeenCalledWith(`/api/v1/acceptance-criteria/${resourceId}`, expect.objectContaining({
      method: "DELETE",
      headers: expect.objectContaining({
        "Idempotency-Key": "criterion-key-1234",
        "If-Match": '"2"',
      }),
    }));
  });

  it("rejects a malformed successful planning response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...goal, version: undefined }, 201)));

    const error = await createGoal({ project_id: projectId, title: "Launch" }, "goal-submit-key-1234")
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
