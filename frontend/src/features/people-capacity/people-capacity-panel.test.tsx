import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { managerActor, renderWithAppProviders } from "@/test/render";
import type { Member } from "@/features/work/contracts";

import { PeopleCapacityPanel } from "./people-capacity-panel";

const organizationId = managerActor.membership.organization_id;
const managerId = managerActor.membership.id;
const employeeId = "44444444-4444-4444-8444-444444444444";
const skillId = "55555555-5555-4555-8555-555555555555";
const personSkillId = "66666666-6666-4666-8666-666666666666";
const taskId = "77777777-7777-4777-8777-777777777777";
const timestamp = "2026-08-24T10:00:00Z";

const skill = {
  id: skillId, organization_id: organizationId, name: "Product design", normalized_name: "product design",
  description: null, active: true, version: 1, created_at: timestamp, updated_at: timestamp,
};
const savedPersonSkill = {
  id: personSkillId, organization_id: organizationId, membership_id: employeeId, skill_id: skillId,
  level: 5, verified_by_membership_id: managerId, verified_at: timestamp, version: 1,
  created_at: timestamp, updated_at: timestamp, active: true, evidence: [{
    id: "88888888-8888-4888-8888-888888888888", organization_id: organizationId, person_skill_id: personSkillId,
    evidence_type: "MANAGER_NOTE", summary: "Delivered launch UI", source_resource_type: "manager_note",
    source_resource_id: managerId, occurred_at: timestamp, created_by_membership_id: managerId, created_at: timestamp,
  }],
};
const workEvidence = {
  id: "99999999-9999-4999-8999-999999999999", organization_id: organizationId, membership_id: employeeId,
  evidence_type: "COMPLETED_TASK", summary: "Completed onboarding task", source_resource_type: "task",
  source_resource_id: taskId, source_resource_version: 3, observed_at: timestamp,
  created_by_membership_id: managerId, created_at: timestamp,
};
const memberPage = {
  items: [
    { membership_id: managerId, display_name: "Demo Manager", role: "MANAGER", is_active: true },
    { membership_id: employeeId, display_name: "Demo Employee", role: "EMPLOYEE", is_active: true },
  ], page: 1, page_size: 100, total: 2,
};
const employeeActor = {
  membership_id: employeeId,
  display_name: "Demo Employee",
  role: "EMPLOYEE" as const,
  is_active: true,
};
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", ...headers },
});

function renderPeopleCapacity(canManage = true, actor: Member = { membership_id: managerId, display_name: "Demo Manager", role: "MANAGER", is_active: true }) {
  return renderWithAppProviders(<PeopleCapacityPanel
    organizationId={organizationId}
    actorMembershipId={actor.membership_id}
    actorMember={actor}
    canManage={canManage}
  />);
}

function stubPeopleApi() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === "/api/v1/members?is_active=true&page=1&page_size=100") return response(memberPage);
    if (path === "/api/v1/skills") return response([skill]);
    if (path === `/api/v1/members/${managerId}/skills`) return response([]);
    if (path === `/api/v1/members/${employeeId}/skills`) return response([]);
    if (path === `/api/v1/members/${managerId}/work-evidence`) return response([]);
    if (path === `/api/v1/members/${employeeId}/work-evidence`) return response([workEvidence]);
    if (path === `/api/v1/members/${employeeId}/skills/${skillId}` && init?.method === "PUT") return response(savedPersonSkill, 200, { ETag: '"1"' });
    throw new Error(`Unexpected request: ${path}`);
  }));
}

describe("PeopleCapacityPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lets a Manager verify a level-5 skill with evidence", async () => {
    stubPeopleApi();
    renderPeopleCapacity();

    await screen.findByText("Demo Employee");
    fireEvent.click(screen.getByRole("button", { name: "Thêm skill" }));
    expect(screen.getByLabelText("Thành viên")).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Thành viên"), { target: { value: employeeId } });
    fireEvent.change(screen.getByLabelText("Skill"), { target: { value: skillId } });
    fireEvent.change(screen.getByLabelText("Mức độ"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Evidence"), { target: { value: "Delivered launch UI" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu skill" }));

    expect(await screen.findByText("Level 5")).toBeVisible();
    expect(screen.getByText("Verified by Demo Manager")).toBeVisible();
    expect(screen.getByRole("button", { name: "Thêm skill" })).toHaveFocus();
  });

  it("closes the skill editor with Escape and restores focus to its trigger", async () => {
    stubPeopleApi();
    renderPeopleCapacity();

    await screen.findByText("Demo Employee");
    const addButton = screen.getByRole("button", { name: "Thêm skill" });
    fireEvent.click(addButton);
    expect(await screen.findByRole("dialog", { name: "Thêm kỹ năng đã xác minh" })).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(addButton).toHaveFocus();
  });

  it("wraps Tab and Shift+Tab focus within the skill editor", async () => {
    stubPeopleApi();
    renderPeopleCapacity();

    await screen.findByText("Demo Employee");
    fireEvent.click(screen.getByRole("button", { name: "Thêm skill" }));
    await screen.findByRole("dialog", { name: "Thêm kỹ năng đã xác minh" });
    const memberField = screen.getByLabelText("Thành viên");
    const saveButton = screen.getByRole("button", { name: "Lưu skill" });
    saveButton.focus();

    fireEvent.keyDown(document, { key: "Tab" });
    expect(memberField).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(saveButton).toHaveFocus();
  });

  it("shows versioned work-outcome provenance without a global score", async () => {
    stubPeopleApi();
    renderPeopleCapacity();

    expect(await screen.findByText("Completed onboarding task")).toBeVisible();
    expect(screen.getByText("task · v3")).toBeVisible();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });

  it("keeps the Employee view read-only", async () => {
    stubPeopleApi();
    renderPeopleCapacity(false);

    expect(await screen.findByText("Demo Manager")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Thêm skill" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Sửa|Xóa/ })).not.toBeInTheDocument();
  });

  it("loads only the authenticated Employee skill record without calling the Manager-only member list", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/skills") return response([skill]);
      if (path === `/api/v1/members/${employeeId}/skills`) return response([{ ...savedPersonSkill, membership_id: employeeId }]);
      if (path === `/api/v1/members/${employeeId}/work-evidence`) return response([workEvidence]);
      throw new Error(`Employee must not request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPeopleCapacity(false, employeeActor);

    expect(await screen.findByRole("heading", { name: "Demo Employee" })).toBeVisible();
    expect(screen.getByText("Completed onboarding task")).toBeVisible();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain("/api/v1/members?is_active=true&page=1&page_size=100");
  });

  it("disables adding a skill when there are no people to assign it to", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/members?is_active=true&page=1&page_size=100") return response({ ...memberPage, items: [], total: 0 });
      if (path === "/api/v1/skills") return response([skill]);
      throw new Error(`Unexpected request: ${path}`);
    }));

    renderPeopleCapacity();

    expect(await screen.findByText("Chưa có thành viên đang hoạt động.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Thêm skill" })).toBeDisabled();
  });

  it("rehydrates an edit with the fresh version after a stale rejection while preserving the draft", async () => {
    const existing = { ...savedPersonSkill, level: 3, version: 1, evidence: [] };
    const fresh = { ...existing, level: 4, version: 2 };
    const mutations: Array<{ ifMatch: string; idempotencyKey: string; payload: unknown }> = [];
    let skillReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/members?is_active=true&page=1&page_size=100") return response(memberPage);
      if (path === "/api/v1/skills") return response([skill]);
      if (path === `/api/v1/members/${managerId}/skills`) return response([]);
      if (path === `/api/v1/members/${employeeId}/skills`) {
        skillReads += 1;
        return response(skillReads === 1 ? [existing] : [fresh]);
      }
      if (path === `/api/v1/members/${managerId}/work-evidence`) return response([]);
      if (path === `/api/v1/members/${employeeId}/work-evidence`) return response([]);
      if (path === `/api/v1/members/${employeeId}/skills/${skillId}` && init?.method === "PUT") {
        const headers = new Headers(init.headers);
        mutations.push({
          ifMatch: headers.get("If-Match") ?? "",
          idempotencyKey: headers.get("Idempotency-Key") ?? "",
          payload: JSON.parse(String(init.body)),
        });
        if (mutations.length === 1) return response({ error: {
          code: "RESOURCE_VERSION_MISMATCH", message_key: "people.error.stale", request_id: "request-stale", field_errors: [], details: {},
        } }, 409);
        return response({ ...fresh, level: 5 }, 200, { ETag: '"3"' });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    renderPeopleCapacity();
    await screen.findByText("Level 3");
    fireEvent.click(screen.getByRole("button", { name: "Sửa" }));
    expect(await screen.findByRole("dialog", { name: "Sửa kỹ năng đã xác minh" })).toBeVisible();
    const skillSelect = screen.getByLabelText("Skill");
    expect(skillSelect).toBeDisabled();
    expect(screen.getByLabelText("Mức độ")).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Mức độ"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Evidence"), { target: { value: "Retain this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu skill" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Dữ liệu kỹ năng đã thay đổi"));
    expect(screen.getByLabelText("Mức độ")).toHaveValue("5");
    expect(screen.getByLabelText("Evidence")).toHaveValue("Retain this draft");
    fireEvent.click(screen.getByRole("button", { name: "Lưu skill" }));
    await screen.findByText("Level 5");
    expect(mutations.map((mutation) => mutation.ifMatch)).toEqual(['"1"', '"2"']);
    expect(mutations.every((mutation) => mutation.idempotencyKey.length > 0)).toBe(true);
    expect(mutations[1]?.payload).toMatchObject({
      skill_id: skillId,
      level: 5,
      evidence: [{
        evidence_type: "MANAGER_NOTE",
        summary: "Retain this draft",
        source_resource_type: "manager_note",
        source_resource_id: managerId,
      }],
    });
  });

  it("maps API field errors to the related editor field", async () => {
    stubPeopleApi();
    const fetchMock = globalThis.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/members?is_active=true&page=1&page_size=100") return response(memberPage);
      if (path === "/api/v1/skills") return response([skill]);
      if (path === `/api/v1/members/${managerId}/skills`) return response([]);
      if (path === `/api/v1/members/${employeeId}/skills`) return response([]);
      if (path === `/api/v1/members/${managerId}/work-evidence`) return response([]);
      if (path === `/api/v1/members/${employeeId}/work-evidence`) return response([workEvidence]);
      if (path === `/api/v1/members/${employeeId}/skills/${skillId}` && init?.method === "PUT") return response({ error: {
        code: "VALIDATION_FAILED", message_key: "common.error.validation", request_id: "request-invalid",
        field_errors: [{ field: "level", code: "invalid_level", message_key: "people.error.level" }], details: {},
      } }, 422);
      throw new Error(`Unexpected request: ${path}`);
    });
    renderPeopleCapacity();
    await screen.findByText("Demo Employee");
    fireEvent.click(screen.getByRole("button", { name: "Thêm skill" }));
    fireEvent.change(screen.getByLabelText("Thành viên"), { target: { value: employeeId } });
    fireEvent.change(screen.getByLabelText("Skill"), { target: { value: skillId } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu skill" }));

    expect(await screen.findByText("Mức độ phải từ 1 đến 5.")).toBeVisible();
    expect(screen.getByLabelText("Mức độ")).toHaveAttribute("aria-describedby", "people-skill-level-error");
  });
});
