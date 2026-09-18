import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { TeamPanel } from "./team-panel";

const projectId = "00000000-0000-4000-8000-000000000001";
const recommendationId = "00000000-0000-4000-8000-000000000010";
const membershipId = "00000000-0000-4000-8000-000000000011";
const minhMembershipId = "00000000-0000-4000-8000-000000000015";
const baoMembershipId = "00000000-0000-4000-8000-000000000016";
const requirementItemId = "00000000-0000-4000-8000-000000000012";
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

  it("offers a manual team recommendation from the confirmed requirement version", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [] };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: [], allocations: [], uncovered: [] });
      throw new Error(path);
    }));

    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);

    expect(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" })).toBeEnabled();
  });

  it("creates recommendation v1 from the exact confirmed requirement version", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [], items: [{
      id: requirementItemId, skill_id: "00000000-0000-4000-8000-000000000013", minimum_level: 3,
      project_week_id: "00000000-0000-4000-8000-000000000014", effort_hours: 8, source_task_ids: [],
    }] };
    const recommendation = recommendationFixture();
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-recommendations` && init?.method === "POST") return json(recommendation, 201);
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: recommendation.alternatives, allocations: [], uncovered: [] });
      if (path === `/api/v1/projects/${projectId}/team`) return json({ memberships: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);

    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));

    const card = (await screen.findByRole("heading", { name: "Phiên bản 1" })).closest("article");
    expect(card).not.toBeNull();
    expect(within(card!).getAllByText("Lan")[0]).toBeVisible();
    const createCall = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([path, init]) => String(path).endsWith("/team-recommendations") && init?.method === "POST");
    expect(createCall?.[1]?.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      requirement_set_id: requirement.id,
      requirement_version: 1,
      policy_version: "ranking-v1",
    });
  });

  it("creates v2 on-card, requires an override reason and leaves v1 read-only", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [], items: [{
      id: requirementItemId, skill_id: "00000000-0000-4000-8000-000000000013", minimum_level: 3,
      project_week_id: "00000000-0000-4000-8000-000000000014", effort_hours: 8, source_task_ids: [],
    }] };
    const v1 = recommendationFixture();
    const v2 = {
      ...v1,
      version: 2,
      selections: [{ requirement_id: requirementItemId, membership_id: minhMembershipId,
        allocated_effort_hours: "8", warning_codes: ["LOWER_RANKED_CANDIDATE"], override_reason: "Phù hợp lịch tuần 2" }],
      diff: { added_membership_ids: [minhMembershipId], removed_membership_ids: [membershipId], before: v1.selections,
        after: [{ requirement_id: requirementItemId, membership_id: minhMembershipId, allocated_effort_hours: "8",
          warning_codes: ["LOWER_RANKED_CANDIDATE"], override_reason: "Phù hợp lịch tuần 2" }] },
    };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-recommendations` && init?.method === "POST") return json(v1, 201);
      if (path === `/api/v1/recommendations/${recommendationId}` && init?.method === "PATCH") return json(v2);
      if (path === `/api/v1/recommendations/${recommendationId}/feedback` && init?.method === "POST") return json({
        id: "00000000-0000-4000-8000-000000000024", recommendation_id: recommendationId,
        version: 2, kind: "override", comment: "Phù hợp lịch tuần 2",
      }, 201);
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: v1.alternatives, allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));
    fireEvent.click(await screen.findByRole("button", { name: "Đổi thành viên" }));

    const memberSelect = screen.getByLabelText("Thành viên");
    expect(within(memberSelect).getByRole("option", { name: /Bảo.*Thiếu kỹ năng đã xác minh/ })).toBeDisabled();
    fireEvent.change(memberSelect, { target: { value: minhMembershipId } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 2" }));
    expect(screen.getByText("Cần nhập lý do khi chọn ứng viên xếp hạng thấp hơn hoặc có cảnh báo.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Lý do thay đổi"), { target: { value: "Phù hợp lịch tuần 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 2" }));

    expect(await screen.findByRole("heading", { name: "Phiên bản 2" })).toBeVisible();
    expect(screen.getByText("Lan → Minh")).toBeVisible();
    expect(screen.getByText("Phiên bản 1 · chỉ đọc")).toBeVisible();
    const patchCall = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([, init]) => init?.method === "PATCH");
    expect(patchCall?.[1]?.headers).toMatchObject({ "If-Match": '"1"', "Idempotency-Key": expect.any(String) });
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ overrides: [{
      requirement_id: requirementItemId,
      selected_membership_id: minhMembershipId,
      override_reason: "Phù hợp lịch tuần 2",
      allocated_effort_hours: "8",
    }] });
    const feedback = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([path]) => String(path).endsWith("/feedback"));
    expect(JSON.parse(String(feedback?.[1]?.body))).toEqual({ version: 2, kind: "override", comment: "Phù hợp lịch tuần 2" });
  });

  it("records override feedback even when the new top-ranked choice needs no reason", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [] };
    const original = recommendationFixture();
    const v1 = { ...original, alternatives: [original.alternatives[1], original.alternatives[0], original.alternatives[2]] };
    const v2 = { ...v1, version: 2, selections: [{ requirement_id: requirementItemId, membership_id: minhMembershipId,
      allocated_effort_hours: "8", warning_codes: [], override_reason: null }], diff: {
      added_membership_ids: [minhMembershipId], removed_membership_ids: [membershipId], before: v1.selections,
      after: [{ requirement_id: requirementItemId, membership_id: minhMembershipId, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
    } };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/team-recommendations") && init?.method === "POST") return json(v1, 201);
      if (path === `/api/v1/recommendations/${recommendationId}` && init?.method === "PATCH") return json(v2);
      if (path.endsWith("/feedback") && init?.method === "POST") return json({
        id: "00000000-0000-4000-8000-000000000026", recommendation_id: recommendationId,
        version: 2, kind: "override", comment: "",
      }, 201);
      if (path.endsWith("/team-requirements")) return json(confirmed);
      if (path.endsWith("/team")) return json({ memberships: [] });
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: v1.alternatives, allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));
    fireEvent.click(await screen.findByRole("button", { name: "Đổi thành viên" }));
    fireEvent.change(screen.getByLabelText("Thành viên"), { target: { value: minhMembershipId } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 2" }));

    expect(await screen.findByRole("heading", { name: "Phiên bản 2" })).toBeVisible();
    const feedback = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([path]) => String(path).endsWith("/feedback"));
    expect(JSON.parse(String(feedback?.[1]?.body))).toEqual({ version: 2, kind: "override", comment: "" });
  });

  it("confirms approval, records accept feedback and shows team membership without assigning tasks", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [] };
    const proposed = recommendationFixture();
    const approved = { ...proposed, status: "APPROVED" };
    const team = { memberships: [{ id: "00000000-0000-4000-8000-000000000020", project_id: projectId,
      membership_id: membershipId, decision_id: "00000000-0000-4000-8000-000000000021", active: true,
      created_at: "2026-09-19T00:00:00Z" }] };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-recommendations` && init?.method === "POST") return json(proposed, 201);
      if (path === `/api/v1/recommendations/${recommendationId}/approve` && init?.method === "POST") return json(approved);
      if (path === `/api/v1/recommendations/${recommendationId}/feedback` && init?.method === "POST") return json({
        id: "00000000-0000-4000-8000-000000000022", recommendation_id: recommendationId,
        version: 1, kind: "accept", comment: "Phù hợp mục tiêu dự án",
      }, 201);
      if (path === `/api/v1/projects/${projectId}/team`) return json(team);
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: proposed.alternatives, allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));
    fireEvent.click(await screen.findByRole("button", { name: "Phê duyệt đội ngũ" }));

    expect(screen.getByText("Phê duyệt chỉ thêm thành viên Project Team và không giao task.")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Ghi chú quyết định"), { target: { value: "Phù hợp mục tiêu dự án" } });
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận phê duyệt" }));

    const currentTeam = (await screen.findByRole("heading", { name: "Đội ngũ hiện tại" })).closest("section");
    expect(currentTeam).not.toBeNull();
    expect(within(currentTeam!).getByText("Lan")).toBeVisible();
    expect(screen.getByText("Không có task nào được giao từ quyết định đội ngũ này.")).toBeVisible();
    const calls = fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>;
    const feedback = calls.find(([path]) => String(path).endsWith("/feedback"));
    expect(JSON.parse(String(feedback?.[1]?.body))).toEqual({ version: 1, kind: "accept", comment: "Phù hợp mục tiêu dự án" });
    expect(calls.some(([path, init]) => String(path).startsWith("/api/v1/tasks") && Boolean(init?.method))).toBe(false);
  });

  it("requires a rejection reason, records reject feedback and creates no team membership", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [] };
    const proposed = recommendationFixture();
    const rejected = { ...proposed, status: "REJECTED" };
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-recommendations` && init?.method === "POST") return json(proposed, 201);
      if (path === `/api/v1/recommendations/${recommendationId}/approve` && init?.method === "POST") return json(rejected);
      if (path === `/api/v1/recommendations/${recommendationId}/feedback` && init?.method === "POST") return json({
        id: "00000000-0000-4000-8000-000000000023", recommendation_id: recommendationId,
        version: 1, kind: "reject", comment: "Cần cân đối lại năng lực",
      }, 201);
      if (path === `/api/v1/projects/${projectId}/team`) return json({ memberships: [] });
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: proposed.alternatives, allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));
    fireEvent.click(await screen.findByRole("button", { name: "Từ chối đề xuất" }));
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận từ chối" }));

    expect(screen.getByText("Hãy nhập lý do từ chối.")).toBeVisible();
    expect(fetch.mock.calls.some(([path, init]) => String(path).endsWith("/approve") && init?.method === "POST")).toBe(false);

    fireEvent.change(screen.getByLabelText("Ghi chú quyết định"), { target: { value: "Cần cân đối lại năng lực" } });
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận từ chối" }));

    expect(await screen.findByText("Đã từ chối")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Đội ngũ hiện tại" })).not.toBeInTheDocument();
    const feedback = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([path]) => String(path).endsWith("/feedback"));
    expect(JSON.parse(String(feedback?.[1]?.body))).toEqual({ version: 1, kind: "reject", comment: "Cần cân đối lại năng lực" });
  });

  it("keeps a successful approval visible when feedback recording fails", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [] };
    const proposed = recommendationFixture();
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-recommendations` && init?.method === "POST") return json(proposed, 201);
      if (path === `/api/v1/recommendations/${recommendationId}/approve` && init?.method === "POST") return json({ ...proposed, status: "APPROVED" });
      if (path === `/api/v1/recommendations/${recommendationId}/feedback` && init?.method === "POST") return json({ error: {
        code: "INTERNAL_ERROR", message_key: "common.error.internal", request_id: "test", field_errors: [], details: {},
      } }, 500);
      if (path === `/api/v1/projects/${projectId}/team`) return json({ memberships: [] });
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: proposed.alternatives, allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));
    fireEvent.click(await screen.findByRole("button", { name: "Phê duyệt đội ngũ" }));
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận phê duyệt" }));

    expect(await screen.findByText("Đã duyệt")).toBeVisible();
    expect(await screen.findByText("Quyết định đã được lưu nhưng chưa thể ghi nhận phản hồi.")).toBeVisible();
    expect(screen.queryByText("Không thể hoàn tất quyết định đội ngũ.")).not.toBeInTheDocument();
  });

  it("keeps unsaved edits on 412 and reapplies them only after comparing with the latest version", async () => {
    const confirmed = { ...requirement, status: "CONFIRMED", incomplete_items: [] };
    const v1 = recommendationFixture();
    const latest = { ...v1, version: 2 };
    const v3 = {
      ...latest, version: 3,
      selections: [{ requirement_id: requirementItemId, membership_id: minhMembershipId,
        allocated_effort_hours: "8", warning_codes: ["LOWER_RANKED_CANDIDATE"], override_reason: "Giữ lựa chọn Minh" }],
      diff: { added_membership_ids: [minhMembershipId], removed_membership_ids: [membershipId], before: latest.selections,
        after: [{ requirement_id: requirementItemId, membership_id: minhMembershipId, allocated_effort_hours: "8",
          warning_codes: ["LOWER_RANKED_CANDIDATE"], override_reason: "Giữ lựa chọn Minh" }] },
    };
    let patchCount = 0;
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === `/api/v1/projects/${projectId}/team-recommendations` && init?.method === "POST") return json(v1, 201);
      if (path === `/api/v1/recommendations/${recommendationId}` && init?.method === "PATCH") {
        patchCount += 1;
        return patchCount === 1 ? json({ error: { code: "RESOURCE_VERSION_MISMATCH", message_key: "common.error.resourceVersionMismatch", request_id: "test", field_errors: [], details: { current_version: 2 } } }, 412) : json(v3);
      }
      if (path === `/api/v1/recommendations/${recommendationId}/feedback` && init?.method === "POST") return json({
        id: "00000000-0000-4000-8000-000000000025", recommendation_id: recommendationId,
        version: 3, kind: "override", comment: "Giữ lựa chọn Minh",
      }, 201);
      if (path === `/api/v1/recommendations/${recommendationId}`) return json(latest);
      if (path === `/api/v1/projects/${projectId}/team-requirements`) return json(confirmed);
      if (path === `/api/v1/projects/${projectId}/team`) return json({ memberships: [] });
      if (path === "/api/v1/skills") return json([]);
      if (path.includes("/weeks")) return json({ items: [], page: 1, page_size: 100, total: 0 });
      if (path.startsWith("/api/v1/tasks?")) return json({ items: [], page: 1, page_size: 20, total: 0 });
      if (path.endsWith("ranking-preview")) return json({ requirement_set_id: confirmed.id, requirement_version: 1, policy_version: "ranking-v1", origin: "DETERMINISTIC", candidates: v1.alternatives, allocations: [], uncovered: [] });
      throw new Error(path);
    });
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TeamPanel projectId={projectId} canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Tạo đề xuất đội ngũ" }));
    fireEvent.click(await screen.findByRole("button", { name: "Đổi thành viên" }));
    fireEvent.change(screen.getByLabelText("Thành viên"), { target: { value: minhMembershipId } });
    fireEvent.change(screen.getByLabelText("Lý do thay đổi"), { target: { value: "Giữ lựa chọn Minh" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 2" }));

    expect(await screen.findByText("Đã có phiên bản 2 mới. Thay đổi của bạn chưa được ghi đè.")).toBeVisible();
    expect(screen.getByLabelText("Lý do thay đổi")).toHaveValue("Giữ lựa chọn Minh");
    fireEvent.click(screen.getByRole("button", { name: "So sánh và áp dụng lại trên phiên bản 2" }));
    expect(screen.getByLabelText("Thành viên")).toHaveValue(minhMembershipId);
    expect(screen.getByLabelText("Lý do thay đổi")).toHaveValue("Giữ lựa chọn Minh");
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 3" }));

    expect(await screen.findByRole("heading", { name: "Phiên bản 3" })).toBeVisible();
    const patchCalls = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).filter(([, init]) => init?.method === "PATCH");
    expect(patchCalls[1][1]?.headers).toMatchObject({ "If-Match": '"2"' });
    expect(JSON.parse(String(patchCalls[1][1]?.body)).overrides[0]).toMatchObject({ selected_membership_id: minhMembershipId, override_reason: "Giữ lựa chọn Minh" });
  });
});

function recommendationFixture() {
  return {
    recommendation_id: recommendationId, version: 1, requirement_set_id: requirement.id,
    requirement_version: 1, policy_version: "ranking-v1", status: "PROPOSED",
    selections: [{ requirement_id: requirementItemId, membership_id: membershipId,
      allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
    alternatives: [{ requirement_id: requirementItemId, membership_id: membershipId,
      display_name: "Lan", eligible: true, hard_failure_codes: [], skill_points: "0.5000",
      capacity_points: "0.3000", evidence_points: "0.1500", familiarity_points: "0.0500",
      total_points: "1.0000", effective_capacity_hours: 40, residual_capacity_hours: 16,
      evidence: [] }, { requirement_id: requirementItemId, membership_id: minhMembershipId,
      display_name: "Minh", eligible: true, hard_failure_codes: [], skill_points: "0.4500",
      capacity_points: "0.2500", evidence_points: "0.1000", familiarity_points: "0.0500",
      total_points: "0.8500", effective_capacity_hours: 40, residual_capacity_hours: 12,
      evidence: [] }, { requirement_id: requirementItemId, membership_id: baoMembershipId,
      display_name: "Bảo", eligible: false, hard_failure_codes: ["SKILL_MISSING"], skill_points: "0.0000",
      capacity_points: "0.3000", evidence_points: "0.0000", familiarity_points: "0.0000",
      total_points: "0.3000", effective_capacity_hours: 40, residual_capacity_hours: 20,
      evidence: [] }],
    uncovered: [], demands: [{ requirement_id: requirementItemId,
      project_week_id: "00000000-0000-4000-8000-000000000014", effort_hours: "8" }],
    diff: null, explanation_status: "NOT_REQUESTED",
  };
}

function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ETag: '"1"' } }); }
function jsonError(status: number) { return json({ error: { code: "RESOURCE_NOT_FOUND", message_key: "error.not_found", request_id: "test", field_errors: [], details: {} } }, status); }
