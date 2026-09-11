import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { TeamPanel } from "./team-panel";

const projectId = "00000000-0000-4000-8000-000000000001";
const requirement = { id: "00000000-0000-4000-8000-000000000002", organization_id: "00000000-0000-4000-8000-000000000003",
  project_id: projectId, version: 1, status: "DRAFT", items: [], incomplete_items: [{ task_id: "00000000-0000-4000-8000-000000000004", reason: "MISSING_REQUIRED_SKILLS" }],
  created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z" };

describe("TeamPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("derives requirements, resolves task labels and blocks confirmation while incomplete", async () => {
    let current: typeof requirement | null = null;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/team-requirements") && !init?.method) return current ? json(current) : jsonError(404);
      if (path.endsWith("/team-requirements") && init?.method === "POST") { current = requirement; return json(current, 201); }
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [{ id: requirement.incomplete_items[0].task_id,
        project_id: projectId, project_week_id: null, milestone_id: null, title: "Discovery", description: null,
        assignee: null, required_skill_labels: [], estimated_effort_hours: null, status: "TO_DO", due_date: null,
        version: 1, created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z" }], page: 1, page_size: 20, total: 1 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: requirement.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: [], allocations: [], uncovered: [] });
      throw new Error(path);
    }));
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo yêu cầu từ task" }));
    expect(await screen.findByText("Discovery")).toBeVisible();
    expect(screen.getByRole("button", { name: "Xác nhận yêu cầu" })).toBeDisabled();
  });

  it("keeps Employee mode read-only", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/team-requirements") ? json(requirement) :
      String(input) === "/api/v1/skills" ? json([]) : String(input).includes("/weeks") ? json({ items: [], page: 1, page_size: 100, total: 0 }) :
      String(input).startsWith("/api/v1/tasks?") ? json({ items: [], page: 1, page_size: 20, total: 0 }) : json({ requirement_set_id: requirement.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: [], allocations: [], uncovered: [] })));
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage={false} />);
    expect(await screen.findByText("Yêu cầu đội ngũ")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Chỉnh sửa yêu cầu" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Xác nhận yêu cầu" })).not.toBeInTheDocument();
  });

  it("confirms the exact visible version with idempotency and If-Match", async () => {
    const complete = { ...requirement, incomplete_items: [] };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-requirements` && init?.method === "PATCH") return json({ ...complete, version: 2, status: "CONFIRMED" });
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(complete);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: complete.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: [], allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Xác nhận yêu cầu" }));
    expect(await screen.findByText("Đã xác nhận v2")).toBeVisible();
    const patchCall = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([, init]) => init?.method === "PATCH");
    expect(patchCall?.[1]?.headers).toMatchObject({ "If-Match": '"1"' });
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ action: "confirm" });
  });

  it("refreshes a stale snapshot through a new immutable revision", async () => {
    const stale = { ...requirement, status: "STALE", incomplete_items: [] };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-requirements` && init?.method === "PATCH") return json({ ...stale, status: "DRAFT", version: 2 });
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(stale);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: stale.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: [], allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Làm mới từ dữ liệu hiện tại" }));
    expect(await screen.findByText("Bản nháp v2")).toBeVisible();
    const patchCall = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ action: "refresh" });
  });
});

function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ETag: '"1"' } }); }
function jsonError(status: number) { return json({ error: { code: "RESOURCE_NOT_FOUND", message_key: "error.not_found", request_id: "test", field_errors: [], details: {} } }, status); }
