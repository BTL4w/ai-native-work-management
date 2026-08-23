import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { managerActor, renderWithAppProviders } from "@/test/render";

import { AssistantShell } from "./assistant-shell";

const conversationId = "11111111-1111-4111-8111-111111111111";
const workflowRunId = "22222222-2222-4222-8222-222222222222";
const messageId = "33333333-3333-4333-8333-333333333333";
const conversation = {
  id: conversationId,
  locale: "vi",
  title: "Kế hoạch ra mắt",
  status: "ACTIVE",
  last_message_sequence: 2,
  last_event_sequence: 4,
  created_at: "2026-08-13T10:00:00Z",
  updated_at: "2026-08-13T10:01:00Z",
};
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});
const noEvents = () => ({ close() {} });
const proposalId = "55555555-5555-4555-8555-555555555555";
const approvalId = "66666666-6666-4666-8666-666666666666";
const proposalContent = {
  project: { title: "Launch", description: null, start_date: "2026-09-01", due_date: "2026-09-14" },
  goal: { title: "Ship safely", description: null, expected_outcomes: ["Live"], target_date: "2026-09-14" },
  milestones: [],
  project_weeks: [{ ref: "w1", week_number: 1, start_date: "2026-09-01", end_date: "2026-09-07", objective: "Prepare" }],
  tasks: [{ ref: "t1", project_week_ref: "w1", milestone_ref: null, title: "Prepare launch", description: null, due_date: "2026-09-07", assignee_membership_id: null, required_skill_labels: ["communication"], estimated_effort_hours: 8, acceptance_criteria: ["Checklist ready"] }],
  dependencies: [],
  assumptions: [],
};
const readyRun = {
  id: workflowRunId,
  project_id: null,
  status: "WAITING_FOR_DECISION",
  workflow_name: "project_planning",
  workflow_version: "1.0.0",
  verifier_version: "1.0.0",
  input_goal_text: "Plan a launch",
  version: 3,
  created_at: "2026-08-13T10:00:00Z",
  updated_at: "2026-08-13T10:01:00Z",
  current_stage: "await_manager_decision",
  current_proposal: {
    proposal_id: proposalId,
    approval_id: approvalId,
    status: "READY_FOR_DECISION",
    version: 2,
    validation_result: { can_approve: true, errors: [], warnings: [] },
    content: proposalContent,
    change_summary: null,
    field_provenance: { default: "AI_PROPOSED" },
    creator_type: "AI_SYSTEM",
    previous_version: null,
  },
  public_timeline: [],
  allowed_actions: ["EDIT_PROPOSAL", "DECIDE_APPROVAL"],
};
const proposalVersion = (currentVersion = 2) => ({
  proposal_id: proposalId,
  workflow_run_id: workflowRunId,
  version: 2,
  current_version: currentVersion,
  content: proposalContent,
  creator_type: "AI_SYSTEM",
});

function proposalSnapshot(readOnly = false) {
  return { conversation, messages: [{
    id: messageId,
    sequence: 1,
    role: "ASSISTANT",
    content_blocks: [{
      kind: "proposal",
      workflow_run_id: workflowRunId,
      proposal_id: proposalId,
      proposal_version: 2,
      approval_id: approvalId,
      state: "READY_FOR_DECISION",
      can_approve: true,
      read_only: readOnly,
      current_version: readOnly ? 3 : null,
      error_codes: [],
      manual_fallback: null,
    }],
    created_at: "2026-08-13T10:01:00Z",
  }] };
}

describe("AssistantShell", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("focuses the fixed composer in the empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ items: [] })));

    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    expect(screen.getByText("Task Management")).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeVisible();
    expect(screen.getByText(managerActor.user.display_name)).toBeVisible();
    const composer = await screen.findByRole("textbox", { name: "Nhắn cho Trợ lý AI" });
    expect(composer).toHaveFocus();
    expect(composer.closest("form")).toHaveClass("assistant-composer");
    expect(screen.queryByText("Hiểu mục tiêu")).not.toBeInTheDocument();
  });

  it("renders the canonical REST transcript chronologically", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/ai/conversations") return response({ items: [conversation] });
      return response({ conversation, messages: [
        { id: messageId, sequence: 2, role: "ASSISTANT", content_blocks: [{ kind: "text", text: "Second response" }], created_at: "2026-08-13T10:01:00Z" },
        { id: workflowRunId, sequence: 1, role: "USER", content_blocks: [{ kind: "text", text: "First request" }], created_at: "2026-08-13T10:00:00Z" },
      ] });
    }));

    const { container } = renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    await screen.findByText("Second response");
    const transcript = container.querySelector(".assistant-transcript");
    expect(transcript?.textContent?.indexOf("First request")).toBeLessThan(
      transcript?.textContent?.indexOf("Second response") ?? 0,
    );
  });

  it("normalizes a malformed success response without exposing unsafe fields", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/ai/conversations") return response({ items: [conversation] });
      return response({ conversation, messages: [{
        id: messageId,
        sequence: 1,
        role: "ASSISTANT",
        content_blocks: [{ kind: "text", text: "Safe", provider_error: "secret provider body" }],
        created_at: "2026-08-13T10:01:00Z",
      }] });
    }));

    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Không thể hoàn tất yêu cầu lúc này");
    expect(document.body.textContent).not.toContain("secret provider body");
  });

  it("preserves the message idempotency key after an uncertain retry", async () => {
    const keys: string[] = [];
    let created = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/ai/conversations" && init?.method === "POST") {
        created = true;
        return response({ ...conversation, last_message_sequence: 0 }, 201);
      }
      if (path === "/api/v1/ai/conversations") return response({ items: created ? [conversation] : [] });
      if (path === `/api/v1/ai/conversations/${conversationId}` && !init?.method) return response({ conversation, messages: [] });
      if (path.endsWith("/messages") && init?.method === "POST") {
        keys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
        if (keys.length === 1) throw new TypeError("connection lost after send");
        return response({ conversation_id: conversationId, message_id: messageId, turn_id: workflowRunId, orchestration_run_id: workflowRunId, status: "QUEUED" }, 202);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    const composer = await screen.findByRole("textbox", { name: "Nhắn cho Trợ lý AI" });
    fireEvent.change(composer, { target: { value: "Plan a launch" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Gửi" }));

    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it("answers a projected manager question as a linked chat turn", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/v1/ai/conversations") return response({ items: [conversation] });
      if (!init?.method) return response({ conversation, messages: [{
        id: messageId,
        sequence: 1,
        role: "ASSISTANT",
        content_blocks: [{ kind: "question", question: "Ngày ra mắt là khi nào?", response_context: { workflow_run_id: workflowRunId } }],
        created_at: "2026-08-13T10:01:00Z",
      }] });
      return response({
        conversation_id: conversationId,
        message_id: messageId,
        turn_id: workflowRunId,
        orchestration_run_id: workflowRunId,
        status: "QUEUED",
      }, 202);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    await screen.findByText("Ngày ra mắt là khi nào?");
    fireEvent.change(screen.getByRole("textbox", { name: "Nhắn cho Trợ lý AI" }), { target: { value: "Ngày 30/9" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/ai/conversations/${conversationId}/messages`,
      expect.objectContaining({ method: "POST" }),
    ));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      message: "Ngày 30/9",
      card_action: { kind: "PLANNING_INPUT", workflow_run_id: workflowRunId },
    });
  });

  it("does not reuse an answered planning question for a later chat message", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/v1/ai/conversations") return response({ items: [conversation] });
      if (!init?.method) return response({ conversation, messages: [
        { id: messageId, sequence: 1, role: "ASSISTANT", content_blocks: [{ kind: "question", question: "Ngày ra mắt?", response_context: { workflow_run_id: workflowRunId } }], created_at: "2026-08-13T10:00:00Z" },
        { id: proposalId, sequence: 2, role: "USER", content_blocks: [{ kind: "text", text: "Ngày 30/9" }], created_at: "2026-08-13T10:01:00Z" },
      ] });
      return response({ conversation_id: conversationId, message_id: messageId, turn_id: workflowRunId, orchestration_run_id: workflowRunId, status: "QUEUED" }, 202);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    await screen.findByText("Ngày ra mắt?");
    fireEvent.change(screen.getByRole("textbox", { name: "Nhắn cho Trợ lý AI" }), { target: { value: "Còn task nào bị chặn?" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).not.toHaveProperty("card_action");
  });

  it("posts Ask AI revision with the projected exact proposal version", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/ai/conversations") return response({ items: [conversation] });
      if (path === `/api/v1/ai/conversations/${conversationId}`) return response(proposalSnapshot());
      if (path === `/api/v1/proposals/${proposalId}/versions/2`) return response(proposalVersion());
      if (path === `/api/v1/workflow-runs/${workflowRunId}`) return response(readyRun);
      if (path.endsWith("/messages") && init?.method === "POST") return response({
        conversation_id: conversationId, message_id: messageId, turn_id: workflowRunId,
        orchestration_run_id: workflowRunId, status: "QUEUED",
      }, 202);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    fireEvent.click(await screen.findByRole("button", { name: "Nhờ AI chỉnh" }));
    fireEvent.change(screen.getByLabelText("Yêu cầu AI chỉnh proposal"), { target: { value: "Dời launch sang tuần 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi yêu cầu chỉnh" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(new Headers(post?.[1]?.headers).get("If-Match")).toBe('"2"');
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      card_action: { kind: "PLANNING_REVISE", workflow_run_id: workflowRunId, proposal_id: proposalId },
    });
  });

  it("edits the proposal inline, expands weeks on demand, and keeps exact-version mutations", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/ai/conversations") return response({ items: [conversation] });
      if (path === `/api/v1/ai/conversations/${conversationId}`) return response(proposalSnapshot());
      if (path === `/api/v1/proposals/${proposalId}/versions/2`) return response(proposalVersion());
      if (path === `/api/v1/workflow-runs/${workflowRunId}`) return response(readyRun);
      if (path === `/api/v1/proposals/${proposalId}` && init?.method === "PATCH") return response({ proposal_id: proposalId, workflow_run_id: workflowRunId, status: "DRAFT", version: 3, content: proposalContent }, 202);
      if (path === `/api/v1/approvals/${approvalId}/decision` && init?.method === "POST") return response({
        approval: { id: approvalId, status: "APPROVED" }, proposal: { id: proposalId, version: 2, status: "APPROVED" },
        created: { project_id: null, goal_id: null, milestone_ids: [], task_ids: [], dependency_ids: [], acceptance_criterion_ids: [] },
        workflow_run_id: workflowRunId, finalization_job_id: "77777777-7777-4777-8777-777777777777",
      });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    fireEvent.click(await screen.findByRole("button", { name: "Chỉnh thủ công" }));
    expect(await screen.findByLabelText("Tên Project")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Mục tiêu tuần")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Tuần 1.*Prepare.*2026-09-01.*2026-09-07/ }));
    expect(screen.getByLabelText("Mục tiêu tuần")).toBeVisible();

    fireEvent.change(await screen.findByLabelText("Tên Project"), { target: { value: "Launch revised" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu version mới" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`/api/v1/proposals/${proposalId}`, expect.objectContaining({ method: "PATCH" })));
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(new Headers(patchCall?.[1]?.headers).get("If-Match")).toBe('"2"');

    fireEvent.click(await screen.findByRole("button", { name: "Phê duyệt kế hoạch" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`/api/v1/approvals/${approvalId}/decision`, expect.objectContaining({ method: "POST" })));
    const approvalCall = fetchMock.mock.calls.find(([path]) => String(path).includes("/approvals/"));
    expect(new Headers(approvalCall?.[1]?.headers).get("If-Match")).toBe('"2"');
  });

  it("renders a superseded proposal read-only and references the current version", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/ai/conversations") return response({ items: [conversation] });
      if (String(input) === `/api/v1/proposals/${proposalId}/versions/2`) return response(proposalVersion(3));
      if (String(input).includes("workflow-runs")) return response({ ...readyRun, current_proposal: { ...readyRun.current_proposal, version: 3 } });
      return response(proposalSnapshot(true));
    }));
    renderWithAppProviders(<AssistantShell actor={managerActor} connectEvents={noEvents} />);

    expect(await screen.findByText("Card này chỉ đọc. Version hiện tại là v3.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Phê duyệt kế hoạch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nhờ AI chỉnh" })).not.toBeInTheDocument();
  });
});
