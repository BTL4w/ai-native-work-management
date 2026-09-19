import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { TaskAssignmentControl } from "./task-assignment-control";

const projectId = "00000000-0000-4000-8000-000000000001";
const taskId = "00000000-0000-4000-8000-000000000002";
const weekId = "00000000-0000-4000-8000-000000000003";
const lanId = "00000000-0000-4000-8000-000000000004";
const minhId = "00000000-0000-4000-8000-000000000005";
const task = {
  id: taskId,
  project_id: projectId,
  project_week_id: weekId,
  milestone_id: null,
  title: "Launch checklist",
  description: null,
  assignee: null,
  required_skill_labels: ["Operations"],
  estimated_effort_hours: 8,
  status: "TO_DO" as const,
  due_date: null,
  version: 3,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
};
const team = { memberships: [{
  id: "00000000-0000-4000-8000-000000000011",
  project_id: projectId,
  membership_id: lanId,
  decision_id: "00000000-0000-4000-8000-000000000012",
  active: true,
  created_at: "2026-09-01T00:00:00Z",
}, {
  id: "00000000-0000-4000-8000-000000000013",
  project_id: projectId,
  membership_id: minhId,
  decision_id: "00000000-0000-4000-8000-000000000012",
  active: false,
  created_at: "2026-09-01T00:00:00Z",
}] };
const members = { items: [
  { membership_id: lanId, display_name: "Lan", role: "EMPLOYEE", is_active: true },
  { membership_id: minhId, display_name: "Minh", role: "EMPLOYEE", is_active: true },
], page: 1, page_size: 100, total: 2 };
const assignedTask = { ...task, assignee: { membership_id: lanId, display_name: "Lan" }, version: 4 };

describe("TaskAssignmentControl", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("assigns only an approved active team member and keeps overload as a warning", async () => {
    const onAssigned = vi.fn();
    const fetch = vi.fn(assignmentFetch());
    vi.stubGlobal("fetch", fetch);
    renderWithAppProviders(<TaskAssignmentControl task={task} onAssigned={onAssigned} onOpenTeam={vi.fn()} onReloadTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Giao task" }));
    const memberSelect = await screen.findByLabelText("Thành viên dự án");
    expect(within(memberSelect).getByRole("option", { name: "Lan" })).toBeVisible();
    expect(within(memberSelect).queryByRole("option", { name: "Minh" })).not.toBeInTheDocument();

    fireEvent.change(memberSelect, { target: { value: lanId } });
    expect(await screen.findByText("35 → 43 giờ / 40 giờ")).toBeVisible();
    expect(screen.getByText(/vượt năng lực tuần/)).toBeVisible();
    expect(await screen.findByText("Operations · Level 4 · 1 bằng chứng")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận giao cho Lan" }));

    expect(await screen.findByText("Đã giao cho Lan")).toBeVisible();
    expect(screen.getByText("36 → 44 giờ / 40 giờ")).toBeVisible();
    expect(onAssigned).toHaveBeenCalledWith(assignedTask);
    const assignmentCall = (fetch.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>).find(([, init]) => init?.method === "POST");
    expect(assignmentCall?.[0]).toBe(`/api/v1/tasks/${taskId}/assign`);
    expect(assignmentCall?.[1]?.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
    expect(JSON.parse(String(assignmentCall?.[1]?.body))).toEqual({ assignee_membership_id: lanId, expected_task_version: 3 });
  });

  it("links an empty approved team to the Project Team tab", async () => {
    const onOpenTeam = vi.fn();
    vi.stubGlobal("fetch", vi.fn(assignmentFetch({ memberships: [] })));
    renderWithAppProviders(<TaskAssignmentControl task={task} onAssigned={vi.fn()} onOpenTeam={onOpenTeam} onReloadTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Giao task" }));
    fireEvent.click(await screen.findByRole("button", { name: "Mở tab Đội ngũ" }));

    expect(onOpenTeam).toHaveBeenCalledOnce();
  });

  it("keeps a legacy Task without a Project Week assignable without inventing overload", async () => {
    const legacyTask = { ...task, project_week_id: null };
    vi.stubGlobal("fetch", vi.fn(assignmentFetch()));
    renderWithAppProviders(<TaskAssignmentControl task={legacyTask} onAssigned={vi.fn()} onOpenTeam={vi.fn()} onReloadTask={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Giao task" }));
    fireEvent.change(await screen.findByLabelText("Thành viên dự án"), { target: { value: lanId } });

    expect(await screen.findByText("Chưa có workload tuần để hiển thị.")).toBeVisible();
    expect(screen.queryByText(/vượt năng lực tuần/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xác nhận giao cho Lan" })).toBeEnabled();
  });

  it("reloads after a stale Task response and reuses one idempotency key per double click", async () => {
    const onReloadTask = vi.fn();
    let resolveAssignment: ((response: Response) => void) | undefined;
    const pendingAssignment = new Promise<Response>((resolve) => { resolveAssignment = resolve; });
    const fetch = vi.fn(assignmentFetch(team, pendingAssignment));
    vi.stubGlobal("fetch", fetch);
    function StaleHarness() {
      const [currentTask, setCurrentTask] = useState(task);
      return <TaskAssignmentControl task={currentTask} onAssigned={vi.fn()} onOpenTeam={vi.fn()} onReloadTask={() => {
        onReloadTask();
        setCurrentTask((current) => ({ ...current, version: current.version + 1 }));
      }} />;
    }
    renderWithAppProviders(<StaleHarness />);

    fireEvent.click(screen.getByRole("button", { name: "Giao task" }));
    fireEvent.change(await screen.findByLabelText("Thành viên dự án"), { target: { value: lanId } });
    const confirm = await screen.findByRole("button", { name: "Xác nhận giao cho Lan" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    resolveAssignment!(errorResponse("RESOURCE_VERSION_MISMATCH", 409));

    fireEvent.click(await screen.findByRole("button", { name: "Tải lại task" }));
    expect(onReloadTask).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Tải lại task" })).not.toBeInTheDocument());
  });

  it("shows a safe API error and restores trigger focus when Escape closes the control", async () => {
    vi.stubGlobal("fetch", vi.fn(assignmentFetch(team, Promise.resolve(errorResponse("ASSIGNMENT_POLICY_DENIED", 403)))));
    renderWithAppProviders(<TaskAssignmentControl task={task} onAssigned={vi.fn()} onOpenTeam={vi.fn()} onReloadTask={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "Giao task" });

    fireEvent.click(trigger);
    const memberSelect = await screen.findByLabelText("Thành viên dự án");
    expect(memberSelect).toHaveFocus();
    fireEvent.change(memberSelect, { target: { value: lanId } });
    fireEvent.click(await screen.findByRole("button", { name: "Xác nhận giao cho Lan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể giao task lúc này");

    fireEvent.keyDown(memberSelect, { key: "Escape" });
    expect(screen.queryByLabelText("Thành viên dự án")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

function assignmentFetch(
  teamResponse = team,
  assignmentResponse: Promise<Response> = Promise.resolve(json({
    task: assignedTask,
    warnings: [{ code: "ASSIGNEE_OVER_CAPACITY" }],
    effective_capacity_hours: 40,
    workload_before_hours: 36,
    workload_after_hours: 44,
  })),
) {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path === `/api/v1/projects/${projectId}/team`) return json(teamResponse);
    if (path === "/api/v1/members?is_active=true&page=1&page_size=100") return json(members);
    if (path === `/api/v1/projects/${projectId}/weeks?page=1&page_size=100`) return json({ items: [{
      id: weekId, project_id: projectId, week_number: 1, start_date: "2026-09-07", end_date: "2026-09-13",
      objective: "Launch", status: "PLANNED", version: 1, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    }], page: 1, page_size: 100, total: 1 });
    if (path === "/api/v1/workload?week_start=2026-09-07") return json([{
      membership_id: lanId, project_week_id: weekId, effective_capacity_hours: 40,
      allocated_effort_hours: 35, residual_capacity_hours: 5, workload_ratio: "0.8750",
    }]);
    if (path === "/api/v1/skills") return json([{
      id: "00000000-0000-4000-8000-000000000020", organization_id: "00000000-0000-4000-8000-000000000021",
      name: "Operations", normalized_name: "operations", description: null, active: true, version: 1,
      created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z",
    }]);
    if (path === `/api/v1/members/${lanId}/skills`) return json([{
      id: "00000000-0000-4000-8000-000000000022", organization_id: "00000000-0000-4000-8000-000000000021",
      membership_id: lanId, skill_id: "00000000-0000-4000-8000-000000000020", level: 4,
      verified_by_membership_id: "00000000-0000-4000-8000-000000000023", verified_at: "2026-09-01T00:00:00Z",
      version: 1, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z", active: true,
      evidence: [{ id: "00000000-0000-4000-8000-000000000024", organization_id: "00000000-0000-4000-8000-000000000021",
        person_skill_id: "00000000-0000-4000-8000-000000000022", evidence_type: "COMPLETED_TASK", summary: "Delivered launch",
        source_resource_type: "task", source_resource_id: taskId, occurred_at: "2026-09-01T00:00:00Z",
        created_by_membership_id: "00000000-0000-4000-8000-000000000023", created_at: "2026-09-01T00:00:00Z" }],
    }]);
    if (path === `/api/v1/tasks/${taskId}/assign` && init?.method === "POST") return assignmentResponse;
    throw new Error(`Unexpected request: ${path}`);
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function errorResponse(code: string, status: number) {
  return json({ error: { code, message_key: "common.error", request_id: "request-1", field_errors: [], details: {} } }, status);
}
