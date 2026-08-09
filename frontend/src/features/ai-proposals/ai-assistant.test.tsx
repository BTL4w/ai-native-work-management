import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { managerActor, renderWithAppProviders } from "@/test/render";

import { AiAssistant } from "./ai-assistant";

const runId = "11111111-1111-4111-8111-111111111111";
const proposalId = "22222222-2222-4222-8222-222222222222";
const approvalId = "33333333-3333-4333-8333-333333333333";
const timestamp = "2026-08-09T10:00:00Z";
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const content = {
  project: { title: "Conference", description: null, start_date: null, due_date: null },
  goal: { title: "Engage customers", description: null, expected_outcomes: [], target_date: null },
  milestones: [],
  tasks: [],
  dependencies: [],
  assumptions: [],
};

const readyRun = {
  id: runId,
  project_id: null,
  status: "WAITING_FOR_DECISION",
  workflow_name: "project_planning",
  workflow_version: "1.0.0",
  verifier_version: "1.0.0",
  input_goal_text: "Plan a conference",
  version: 3,
  created_at: timestamp,
  updated_at: timestamp,
  current_stage: "await_manager_decision",
  current_proposal: {
    proposal_id: proposalId,
    approval_id: approvalId,
    status: "READY_FOR_DECISION",
    version: 2,
    validation_result: { can_approve: true, errors: [], warnings: [] },
    content,
    change_summary: null,
    field_provenance: { default: "AI_PROPOSED" },
    creator_type: "AI_SYSTEM",
    previous_version: null,
  },
  public_timeline: [],
  allowed_actions: ["EDIT_PROPOSAL", "DECIDE_APPROVAL"],
};

describe("AiAssistant", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("starts a natural-language planning run and selects it", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const path = String(input);
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [] });
      if (path === "/api/v1/ai/planning-runs" && init?.method === "POST") {
        return response({ run_id: runId, status: "QUEUED", version: 1 }, 202);
      }
      if (path === `/api/v1/workflow-runs/${runId}`) {
        return response({ ...readyRun, status: "QUEUED", current_proposal: null,
          current_stage: "queued", allowed_actions: [] });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );
    fireEvent.change(await screen.findByLabelText("Yêu cầu lập kế hoạch"), {
      target: { value: "Plan a conference" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Gửi yêu cầu" }));

    expect(await screen.findByText("Đang chờ xử lý")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/ai/planning-runs",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("shows structured review and decides the exact proposal version", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      const path = String(input);
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [readyRun] });
      if (path === `/api/v1/workflow-runs/${runId}`) return response(readyRun);
      if (path === `/api/v1/approvals/${approvalId}/decision`) {
        return response({
          approval: { id: approvalId, status: "APPROVED" },
          proposal: { id: proposalId, version: 2, status: "APPROVED" },
          created: {
            project_id: "44444444-4444-4444-8444-444444444444",
            goal_id: null,
            milestone_ids: [], task_ids: [], dependency_ids: [],
            acceptance_criterion_ids: [],
          },
          workflow_run_id: runId,
          finalization_job_id: "55555555-5555-4555-8555-555555555555",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));

    expect(await screen.findByRole("heading", { name: "Proposal v2" })).toBeVisible();
    expect(screen.getByText("AI đề xuất")).toBeVisible();
    const approveButton = screen.getByRole("button", { name: "Phê duyệt" });
    approveButton.focus();
    fireEvent.click(approveButton);
    expect(screen.getByRole("dialog")).toHaveTextContent("Proposal v2");
    expect(screen.getByRole("button", { name: "Xác nhận phê duyệt" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Hủy" }));
    expect(approveButton).toHaveFocus();
    fireEvent.click(approveButton);
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận phê duyệt" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/approvals/${approvalId}/decision`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "If-Match": '"2"' }),
      }),
    ));
    expect(await screen.findByText("Đã tạo Project")).toBeVisible();
  });

  it("pins the reviewed approval and version while SSE refreshes the snapshot", async () => {
    let refreshSnapshot = false;
    let advance: (() => void) | undefined;
    const replacementApprovalId = "66666666-6666-4666-8666-666666666666";
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [readyRun] });
      if (path === `/api/v1/workflow-runs/${runId}`) {
        return response(refreshSnapshot ? {
          ...readyRun,
          current_proposal: {
            ...readyRun.current_proposal,
            approval_id: replacementApprovalId,
            version: 3,
          },
        } : readyRun);
      }
      if (path === `/api/v1/approvals/${approvalId}/decision`) {
        expect(new Headers(init?.headers).get("If-Match")).toBe('"2"');
        return response({
          approval: { id: approvalId, status: "REJECTED" },
          proposal: { id: proposalId, version: 2, status: "REJECTED" },
          created: { project_id: null, goal_id: null, milestone_ids: [], task_ids: [], dependency_ids: [], acceptance_criterion_ids: [] },
          workflow_run_id: runId,
          finalization_job_id: "55555555-5555-4555-8555-555555555555",
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={(options) => {
        advance = () => options.onSequence(4);
        return { close: vi.fn() };
      }} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Từ chối" }));
    refreshSnapshot = true;
    act(() => advance?.());
    await screen.findByRole("heading", { name: "Proposal v3" });

    expect(screen.getByRole("dialog")).toHaveTextContent("Proposal v2");
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận từ chối" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/approvals/${approvalId}/decision`,
      expect.any(Object),
    ));
  });

  it("disables approval for stale proposals and offers canonical reload", async () => {
    const stale = {
      ...readyRun,
      current_proposal: { ...readyRun.current_proposal, status: "STALE", approval_id: null },
      allowed_actions: ["EDIT_PROPOSAL"],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) =>
      response(String(input).includes(`/${runId}`) ? stale : { items: [stale] })));

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));

    expect(await screen.findByText("Proposal đã cũ")).toBeVisible();
    expect(screen.getByRole("button", { name: "Phê duyệt" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Từ chối" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tải lại dữ liệu" })).toBeEnabled();
  });

  it("resumes a NEEDS_INPUT checkpoint through the manager message endpoint", async () => {
    const needsInput = {
      ...readyRun,
      status: "NEEDS_INPUT",
      current_stage: "await_manager_input",
      current_proposal: null,
      allowed_actions: ["MESSAGE"],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [needsInput] });
      if (path === `/api/v1/workflow-runs/${runId}`) return response(needsInput);
      if (path === `/api/v1/workflow-runs/${runId}/messages` && init?.method === "POST") {
        return response({ run_id: runId, status: "RUNNING", version: 4 }, 202);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));
    fireEvent.change(await screen.findByLabelText("Thông tin bổ sung"), {
      target: { value: "Budget is approved" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Xác nhận và tiếp tục" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/workflow-runs/${runId}/messages`,
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("supports structured DRAFT editing and blocks approval without an assignee", async () => {
    const draft = {
      ...readyRun,
      current_proposal: {
        ...readyRun.current_proposal,
        approval_id: null,
        status: "DRAFT",
        creator_type: "HUMAN_MANAGER",
        content: {
          ...content,
          tasks: [{
            ref: "t1", milestone_ref: null, title: "Book venue", description: null,
            due_date: null, assignee_membership_id: null, acceptance_criteria: ["Venue selected"],
          }],
        },
      },
      allowed_actions: ["EDIT_PROPOSAL"],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [draft] });
      if (path === `/api/v1/workflow-runs/${runId}`) return response(draft);
      if (path.startsWith("/api/v1/members?")) {
        return response({ items: [], page: 1, page_size: 100, total: 0 });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));

    expect(await screen.findByText("Manager đã chỉnh")).toBeVisible();
    expect(screen.getByRole("button", { name: "Phê duyệt" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Chỉnh tất cả" }));
    expect(await screen.findByRole("heading", { name: "Chỉnh proposal có cấu trúc" })).toBeVisible();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it("shows SSE recovery and a safe manual fallback for failed workflows", async () => {
    const failed = {
      ...readyRun,
      status: "FAILED",
      current_stage: "manual_fallback",
      current_proposal: null,
      allowed_actions: [],
    };
    const onContinueManually = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/ai/planning-runs" && init?.method === "POST") {
        return response({ run_id: runId, status: "QUEUED", version: 2 }, 202);
      }
      return response(path.includes(`/${runId}`) ? failed : { items: [failed] });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(
      <AiAssistant
        actor={managerActor}
        connectEvents={(options) => {
          options.onStatus("reconnecting");
          return { close: vi.fn() };
        }}
        onContinueManually={onContinueManually}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));

    expect(await screen.findByText(/Đang kết nối lại/)).toBeVisible();
    expect(screen.queryByText(/provider/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tiếp tục thủ công" }));
    expect(onContinueManually).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/ai/planning-runs",
      expect.objectContaining({ method: "POST" }),
    ));
  });

  it("shows a safe error when a refreshed snapshot violates the public contract", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [readyRun] });
      if (path === `/api/v1/workflow-runs/${runId}`) {
        return response({ ...readyRun, current_proposal: {
          ...readyRun.current_proposal,
          content: { ...content, assumptions: [{ unexpected: "provider detail" }] },
        } });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Plan a conference/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể hoàn tất yêu cầu lúc này.");
    expect(screen.queryByText("provider detail")).not.toBeInTheDocument();
  });
});
