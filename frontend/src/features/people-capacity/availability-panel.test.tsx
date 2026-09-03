import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Member } from "@/features/work/contracts";
import { managerActor, renderWithAppProviders } from "@/test/render";

import { AvailabilityPanel, availabilityKeys, localWeekStart } from "./availability-panel";

const organizationId = managerActor.membership.organization_id;
const managerId = managerActor.membership.id;
const employeeId = "44444444-4444-4444-8444-444444444444";
const projectWeekId = "55555555-5555-4555-8555-555555555555";
const capacityId = "66666666-6666-4666-8666-666666666666";
const leaveId = "77777777-7777-4777-8777-777777777777";
const timestamp = "2026-08-24T10:00:00Z";
const members: Member[] = [
  { membership_id: managerId, display_name: "Demo Manager", role: "MANAGER", is_active: true },
  { membership_id: employeeId, display_name: "Demo Employee", role: "EMPLOYEE", is_active: true },
];

const capacity = {
  id: capacityId, organization_id: organizationId, membership_id: employeeId, kind: "DEFAULT",
  hours: 40, effective_from: "2000-01-01", effective_to: "2099-12-31", week_start: null,
  version: 1, created_at: timestamp, updated_at: timestamp,
};
const leave = {
  id: leaveId, organization_id: organizationId, membership_id: employeeId,
  start_date: "2026-08-24", end_date: "2026-08-24", unavailable_hours: 8,
  version: 1, created_at: timestamp, updated_at: timestamp,
};
const workload = {
  membership_id: employeeId, project_week_id: projectWeekId, effective_capacity_hours: 32,
  allocated_effort_hours: 24, residual_capacity_hours: 8, workload_ratio: "0.75",
};
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", ...headers },
});

function availabilityResponse(path: string, values: { capacity?: unknown[]; leave?: unknown[]; workload?: unknown[] } = {}) {
  if (path.startsWith("/api/v1/capacity")) return response(values.capacity ?? [capacity]);
  if (path.startsWith("/api/v1/leave")) return response(values.leave ?? [leave]);
  if (path.startsWith("/api/v1/workload")) return response(values.workload ?? [workload]);
  throw new Error(`Unexpected request: ${path}`);
}

function renderAvailability(options: { canManage?: boolean; locale?: "vi" | "en"; actorMembershipId?: string } = {}) {
  const canManage = options.canManage ?? true;
  const actorMembershipId = options.actorMembershipId ?? managerId;
  return renderWithAppProviders(<AvailabilityPanel
    actorMembershipId={actorMembershipId}
    canManage={canManage}
    initialWeekStart="2026-08-24"
    members={canManage ? members : members.filter((member) => member.membership_id === actorMembershipId)}
    organizationId={organizationId}
  />, options.locale);
}

describe("AvailabilityPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("uses the tenant-scoped workload query key", () => {
    expect(availabilityKeys.workload(organizationId, managerId, "2026-08-24")).toEqual([
      "people-capacity", organizationId, managerId, "workload", "2026-08-24",
    ]);
  });

  it("shows derived workload and does not offer a workload input", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input))));
    renderAvailability();

    expect(await screen.findByText("24 / 32 giờ")).toBeVisible();
    expect(screen.getByText("Còn 8 giờ")).toBeVisible();
    expect(screen.getByText(/Nghỉ 8 giờ/)).toBeVisible();
    expect(screen.getByText("75% capacity hiệu dụng đã được phân bổ.")).toBeVisible();
    expect(screen.queryByLabelText("Nhập workload")).not.toBeInTheDocument();
  });

  it("distinguishes zero capacity from overload", async () => {
    const zero = { ...workload, effective_capacity_hours: 0, allocated_effort_hours: 0, residual_capacity_hours: 0, workload_ratio: null };
    const overloaded = { ...workload, membership_id: managerId, effective_capacity_hours: 40, allocated_effort_hours: 48, residual_capacity_hours: 0, workload_ratio: "1.2" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), {
      capacity: [capacity, { ...capacity, id: projectWeekId, membership_id: managerId }],
      leave: [], workload: [zero, overloaded],
    })));
    renderAvailability();

    expect(await screen.findByText("Không có capacity khả dụng")).toBeVisible();
    expect(screen.getByText("Quá tải 8 giờ")).toBeVisible();
    expect(screen.getByText("120% capacity hiệu dụng đã được phân bổ.")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "120% capacity hiệu dụng đã được phân bổ." })).toHaveAttribute("aria-valuetext", "120% capacity hiệu dụng đã được phân bổ.");
  });

  it("uses the browser-local Monday at the UTC week boundary", () => {
    vi.stubEnv("TZ", "Asia/Ho_Chi_Minh");
    expect(localWeekStart(new Date("2026-08-30T18:00:00.000Z"))).toBe("2026-08-31");
  });

  it("shows only capacity entries intersecting the selected week", async () => {
    const historicalOverride = { ...capacity, id: "88888888-8888-4888-8888-888888888888", kind: "OVERRIDE", hours: 60, effective_from: "2026-08-17", effective_to: "2026-08-23", week_start: "2026-08-17" };
    const midweekDefault = { ...capacity, id: "99999999-9999-4999-8999-999999999999", hours: 36, effective_from: "2026-08-26", effective_to: "2026-12-31" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), {
      capacity: [historicalOverride, midweekDefault], workload: [],
    })));
    renderAvailability();

    expect(await screen.findByText(/Capacity 36 giờ/)).toBeVisible();
    expect(screen.queryByText("Tuần này · 60 giờ")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Sửa capacity/ })).toHaveLength(1);
  });

  it("does not infer base capacity from effective capacity and leave", async () => {
    const zeroCapacity = { ...workload, effective_capacity_hours: 0, allocated_effort_hours: 0, residual_capacity_hours: 0, workload_ratio: null };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), {
      capacity: [], leave: [leave], workload: [zeroCapacity],
    })));
    renderAvailability();

    expect(await screen.findByText(/Capacity 0 giờ · Nghỉ 8 giờ/)).toBeVisible();
  });

  it("keeps capacity and leave editable when the week has no Project Week workload", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), { workload: [] })));
    renderAvailability();

    expect(await screen.findByRole("heading", { name: "Demo Employee" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Sửa capacity của Demo Employee" })).toBeVisible();
    expect(screen.getByText("Chưa có workload cho tuần này.")).toBeVisible();
  });

  it("apportions leave that crosses the selected week boundary", async () => {
    const crossingLeave = { ...leave, start_date: "2026-08-21", end_date: "2026-08-24", unavailable_hours: 32 };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), { leave: [crossingLeave] })));
    renderAvailability();

    expect(await screen.findByText(/Nghỉ 8 giờ/)).toBeVisible();
    expect(screen.queryByText(/Nghỉ 32 giờ/)).not.toBeInTheDocument();
  });

  it("caps aggregate leave at the backend weekly limit", async () => {
    const secondLeave = { ...leave, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", unavailable_hours: 100 };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), {
      leave: [{ ...leave, unavailable_hours: 100 }, secondLeave],
    })));
    renderAvailability();

    expect(await screen.findByText(/Nghỉ 168 giờ/)).toBeVisible();
    expect(screen.queryByText(/Nghỉ 200 giờ/)).not.toBeInTheDocument();
  });

  it("groups multiple Project Week workloads into distinct sections for one member", async () => {
    const otherWeek = { ...workload, project_week_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", allocated_effort_hours: 8, residual_capacity_hours: 24, workload_ratio: "0.25" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input), { workload: [workload, otherWeek] })));
    renderAvailability();

    const card = await screen.findByRole("heading", { name: "Demo Employee" });
    expect(within(card.closest("article")!).getAllByRole("region")).toHaveLength(2);
    expect(screen.getByText(`Tuần dự án ${projectWeekId}`)).toBeVisible();
    expect(screen.getByText("Tuần dự án bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")).toBeVisible();
  });

  it("moves one calendar week at a time and reloads the workload", async () => {
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      requests.push(path);
      return availabilityResponse(path);
    }));
    renderAvailability();
    await screen.findByText("24 / 32 giờ");

    fireEvent.click(screen.getByRole("button", { name: "Tuần sau" }));

    expect(await screen.findByText(/31\/08\/2026 – 06\/09\/2026/)).toBeVisible();
    await waitFor(() => expect(requests.some((path) => path.includes("week_start=2026-08-31"))).toBe(true));
  });

  it("lets a Manager create a weekly capacity override and leave", async () => {
    const mutations: Array<{ path: string; body: Record<string, unknown>; key: string }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (!init?.method || init.method === "GET") return availabilityResponse(path);
      const headers = new Headers(init.headers);
      mutations.push({ path, body: JSON.parse(String(init.body)), key: headers.get("Idempotency-Key") ?? "" });
      if (path === "/api/v1/capacity") return response({ ...capacity, kind: "OVERRIDE", week_start: "2026-08-24", effective_from: "2026-08-24", effective_to: "2026-08-30", hours: 36 }, 201, { ETag: '"1"' });
      if (path === "/api/v1/leave") return response(leave, 201, { ETag: '"1"' });
      throw new Error(`Unexpected mutation: ${path}`);
    }));
    renderAvailability();
    await screen.findByText("24 / 32 giờ");

    fireEvent.click(screen.getByRole("button", { name: "Thiết lập capacity" }));
    const capacityDialog = await screen.findByRole("dialog", { name: "Thiết lập capacity" });
    fireEvent.change(within(capacityDialog).getByLabelText("Thành viên"), { target: { value: employeeId } });
    fireEvent.change(within(capacityDialog).getByLabelText("Loại capacity"), { target: { value: "OVERRIDE" } });
    fireEvent.change(within(capacityDialog).getByLabelText("Số giờ"), { target: { value: "36" } });
    fireEvent.click(within(capacityDialog).getByRole("button", { name: "Lưu capacity" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Thiết lập capacity" })).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Thêm lịch nghỉ" }));
    const leaveDialog = await screen.findByRole("dialog", { name: "Thêm lịch nghỉ" });
    fireEvent.change(within(leaveDialog).getByLabelText("Thành viên"), { target: { value: employeeId } });
    fireEvent.change(within(leaveDialog).getByLabelText("Số giờ nghỉ"), { target: { value: "8" } });
    fireEvent.click(within(leaveDialog).getByRole("button", { name: "Lưu lịch nghỉ" }));

    await waitFor(() => expect(mutations).toHaveLength(2));
    expect(mutations[0]).toMatchObject({ path: "/api/v1/capacity", body: { membership_id: employeeId, kind: "OVERRIDE", week_start: "2026-08-24", hours: 36 } });
    expect(mutations[1]).toMatchObject({ path: "/api/v1/leave", body: { membership_id: employeeId, start_date: "2026-08-24", end_date: "2026-08-24", unavailable_hours: 8 } });
    expect(mutations.every((mutation) => mutation.key.length >= 16)).toBe(true);
  });

  it("keeps Employee availability read-only and limits reads to the actor", async () => {
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      requests.push(path);
      return availabilityResponse(path);
    }));
    renderAvailability({ canManage: false, actorMembershipId: employeeId });

    expect(await screen.findByText("24 / 32 giờ")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Thiết lập capacity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thêm lịch nghỉ" })).not.toBeInTheDocument();
    const availabilityRequests = requests.filter((path) => /^\/api\/v1\/(capacity|leave|workload)/.test(path));
    expect(availabilityRequests).toHaveLength(3);
    expect(availabilityRequests.every((path) => path.includes(`membership_id=${employeeId}`))).toBe(true);
  });

  it("reloads fresh availability after a stale edit rejection", async () => {
    let capacityReads = 0;
    let capacityWrites = 0;
    const bodies: Array<Record<string, unknown>> = [];
    const datedCapacity = { ...capacity, effective_from: "2026-07-01", effective_to: "2026-12-31" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.startsWith("/api/v1/capacity") && (!init?.method || init.method === "GET")) {
        capacityReads += 1;
        return response([{ ...datedCapacity, hours: capacityReads === 1 ? 40 : 44, version: capacityReads }]);
      }
      if (path === "/api/v1/capacity" && init?.method === "POST") {
        capacityWrites += 1;
        bodies.push(JSON.parse(String(init.body)));
        if (capacityWrites === 1) return response({ error: {
          code: "RESOURCE_VERSION_MISMATCH", message_key: "common.error.resourceVersionMismatch",
          request_id: "request-stale", field_errors: [], details: { current_version: 2 },
        } }, 412);
        return response({ ...datedCapacity, hours: 44, version: 3 }, 200, { ETag: '"3"' });
      }
      return availabilityResponse(path);
    }));
    renderAvailability();
    await screen.findByText("24 / 32 giờ");

    fireEvent.click(screen.getByRole("button", { name: "Sửa capacity của Demo Employee" }));
    const dialog = await screen.findByRole("dialog", { name: "Sửa capacity" });
    fireEvent.change(within(dialog).getByLabelText("Số giờ"), { target: { value: "36" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Lưu capacity" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Dữ liệu availability đã thay đổi");
    expect(within(dialog).getByLabelText("Số giờ")).toHaveValue(44);
    expect(capacityReads).toBeGreaterThan(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Lưu capacity" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ hours: 44, effective_from: "2026-07-01", effective_to: "2026-12-31" });
  });

  it("supports keyboard focus and Escape in availability dialogs", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input))));
    renderAvailability();
    await screen.findByText("24 / 32 giờ");
    const trigger = screen.getByRole("button", { name: "Thiết lập capacity" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Thiết lập capacity" });
    const memberField = within(dialog).getByLabelText("Thành viên");
    const saveButton = within(dialog).getByRole("button", { name: "Lưu capacity" });
    expect(memberField).toHaveFocus();
    saveButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(memberField).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Thiết lập capacity" })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("renders the workload explanation in English", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => availabilityResponse(String(input))));
    renderAvailability({ locale: "en" });

    expect(await screen.findByText("24 / 32 hours")).toBeVisible();
    expect(screen.getByText("8 hours remaining")).toBeVisible();
    expect(screen.getByText("75% of effective capacity is allocated.")).toBeVisible();
  });
});
