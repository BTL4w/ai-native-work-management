import { afterEach, describe, expect, it, vi } from "vitest";

import { confirmRequirements, deriveRequirements, getProjectTeam, getRankingPreview, getRecommendation, getRecommendationVersion, getRequirements, listAllProjectTasks, refreshRequirements, reviseRequirements } from "./api";

const projectId = "00000000-0000-4000-8000-000000000003";
const setId = "00000000-0000-4000-8000-000000000001";
const responseBody = { id: setId, organization_id: "00000000-0000-4000-8000-000000000002", project_id: projectId,
  version: 1, status: "DRAFT", items: [], incomplete_items: [], created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z" };

describe("project team api", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses exact project routes and concurrency headers", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(responseBody), { status: 200, headers: { "Content-Type": "application/json", ETag: '"1"' } }));
    vi.stubGlobal("fetch", fetch);
    await getRequirements(projectId);
    await deriveRequirements(projectId, "derive-key");
    await reviseRequirements(projectId, { action: "revise", items: [], incomplete_items: [] }, 1, "revise-key");
    await confirmRequirements(projectId, 1, "confirm-key");
    await refreshRequirements(projectId, 1, "refresh-key");
    const calls = fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>;
    expect(calls.map(([requestPath]) => requestPath)).toEqual(Array(5).fill(`/api/v1/projects/${projectId}/team-requirements`));
    expect(calls[2][1]?.headers).toMatchObject({ "If-Match": '"1"', "Idempotency-Key": "revise-key" });
  });

  it("loads every Project Task page for requirement source resolution", async () => {
    const task = { id: "00000000-0000-4000-8000-000000000099", project_id: projectId, project_week_id: null,
      milestone_id: null, title: "Later task", description: null, assignee: null, required_skill_labels: [],
      estimated_effort_hours: null, status: "TO_DO", due_date: null, version: 1,
      created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z" };
    const firstTask = { ...task, id: "00000000-0000-4000-8000-000000000098", title: "First task" };
    const fetch = vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(String(input).includes("page=1&")
      ? { items: [firstTask], page: 1, page_size: 100, total: 2 }
      : { items: [task], page: 2, page_size: 100, total: 2 }), { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    expect(await listAllProjectTasks(projectId)).toEqual([firstTask, task]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("loads the read-only deterministic ranking projection", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ requirement_set_id: setId,
      requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: [], allocations: [], uncovered: [] }),
      { headers: { "Content-Type": "application/json" } })));
    await getRankingPreview(projectId);
    expect(fetch).toHaveBeenCalledWith(`/api/v1/projects/${projectId}/team-requirements/ranking-preview`, expect.anything());
  });

  it("loads approved Project Team memberships through the exact project route", async () => {
    const currentTeam = { memberships: [{
      id: "00000000-0000-4000-8000-000000000031",
      project_id: projectId,
      membership_id: "00000000-0000-4000-8000-000000000032",
      decision_id: "00000000-0000-4000-8000-000000000033",
      active: true,
      created_at: "2026-09-20T00:00:00Z",
    }] };
    const fetch = vi.fn(async () => new Response(JSON.stringify(currentTeam), { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);

    expect(await getProjectTeam(projectId)).toEqual(currentTeam);
    expect(fetch).toHaveBeenCalledWith(`/api/v1/projects/${projectId}/team`, expect.anything());
  });

  it("loads the current and an immutable recommendation version through their exact routes", async () => {
    const recommendationId = "00000000-0000-4000-8000-000000000010";
    const recommendation = { recommendation_id: recommendationId, version: 2, requirement_set_id: setId,
      requirement_version: 1, policy_version: "ranking-v1", status: "PROPOSED", selections: [], alternatives: [],
      uncovered: [], demands: [], diff: null, explanation_status: "NOT_REQUESTED" };
    const fetch = vi.fn(async () => new Response(JSON.stringify(recommendation), { headers: { "Content-Type": "application/json", ETag: '"2"' } }));
    vi.stubGlobal("fetch", fetch);

    await getRecommendation(recommendationId);
    await getRecommendationVersion(recommendationId, 1);

    const calls = fetch.mock.calls as unknown as Array<[RequestInfo | URL]>;
    expect(calls.map(([requestPath]) => requestPath)).toEqual([
      `/api/v1/recommendations/${recommendationId}`,
      `/api/v1/recommendations/${recommendationId}/versions/1`,
    ]);
  });
});
