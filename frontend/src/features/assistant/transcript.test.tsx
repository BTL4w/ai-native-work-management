import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import type { AssistantMessage } from "./contracts";
import { Transcript } from "./transcript";

const callbacks = {
  onEdit: vi.fn(),
  onRevise: vi.fn(),
  onApprove: vi.fn(),
  onReject: vi.fn(),
};

function activityMessage(
  sequence: number,
  labelKey: string,
  workflowRunId?: string,
): AssistantMessage {
  const activityBlock = {
    kind: "activity",
    label_key: labelKey,
    status: "COMPLETED",
    agent_id: "planning",
    ...(workflowRunId ? { workflow_run_id: workflowRunId } : {}),
  } as unknown as AssistantMessage["content_blocks"][number];
  return {
    id: `00000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`,
    sequence,
    role: "ASSISTANT",
    content_blocks: [activityBlock],
    created_at: `2026-08-18T00:00:${sequence.toString().padStart(2, "0")}Z`,
  };
}

describe("Transcript", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders consecutive workflow activities as one visual card", () => {
    renderWithAppProviders(<Transcript
      messages={[
        activityMessage(1, "ai.activity.workflow_policy_checked"),
        activityMessage(2, "ai.activity.workflow_context_loaded"),
        activityMessage(3, "ai.activity.workflow_generating"),
        activityMessage(4, "ai.activity.workflow_schema_validating"),
        activityMessage(5, "ai.activity.workflow_verifying"),
        activityMessage(6, "ai.activity.workflow_generating"),
        activityMessage(7, "ai.activity.workflow_schema_validating"),
        activityMessage(8, "ai.activity.workflow_verifying"),
        activityMessage(9, "ai.activity.workflow_persisting_proposal"),
      ]}
      canManage
      {...callbacks}
    />);

    expect(screen.getAllByText("Trợ lý đang xử lý một bước an toàn")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Xem chi tiết hoạt động" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Xem chi tiết hoạt động" }));
    expect(screen.getByText("9 bước xử lý dữ liệu công việc đã được kiểm soát")).toBeVisible();
  });

  it("does not group activities across a real conversation message", () => {
    const userMessage: AssistantMessage = {
      id: "10000000-0000-4000-8000-000000000002",
      sequence: 2,
      role: "USER",
      content_blocks: [{ kind: "text", text: "Hãy chỉnh lại kế hoạch" }],
      created_at: "2026-08-18T00:00:02Z",
    };

    renderWithAppProviders(<Transcript
      messages={[
        activityMessage(1, "ai.activity.workflow_generating"),
        userMessage,
        activityMessage(3, "ai.activity.workflow_verifying"),
      ]}
      canManage
      {...callbacks}
    />);

    expect(screen.getByText("Hãy chỉnh lại kế hoạch")).toBeVisible();
    expect(screen.getAllByText("Trợ lý đang xử lý một bước an toàn")).toHaveLength(2);
  });

  it("groups one workflow even when a proposal boundary separates its activities", () => {
    const workflowRunId = "20000000-0000-4000-8000-000000000001";
    const proposalBoundary: AssistantMessage = {
      id: "20000000-0000-4000-8000-000000000002",
      sequence: 2,
      role: "ASSISTANT",
      content_blocks: [{
        kind: "planning_run",
        workflow_run_id: workflowRunId,
        status: "AWAITING_HUMAN",
      }],
      created_at: "2026-08-18T00:00:02Z",
    };

    renderWithAppProviders(<Transcript
      messages={[
        activityMessage(1, "ai.activity.workflow_generating", workflowRunId),
        proposalBoundary,
        activityMessage(3, "ai.activity.workflow_waiting_for_decision", workflowRunId),
      ]}
      canManage
      {...callbacks}
    />);

    expect(screen.getByText("Workflow lập kế hoạch: AWAITING_HUMAN")).toBeVisible();
    expect(screen.getAllByText("Trợ lý đang xử lý một bước an toàn")).toHaveLength(1);
  });

  it("keeps one immutable history card per proposal version", async () => {
    const proposalId = "30000000-0000-4000-8000-000000000001";
    const workflowRunId = "30000000-0000-4000-8000-000000000002";
    const content = (title: string) => ({
      project: { title, description: null, start_date: null, due_date: null },
      goal: { title, description: null, expected_outcomes: [], target_date: null },
      milestones: [],
      project_weeks: [],
      tasks: [],
      dependencies: [],
      assumptions: [],
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const version = String(input).endsWith("/versions/1") ? 1 : 2;
      return new Response(JSON.stringify({
        proposal_id: proposalId,
        workflow_run_id: workflowRunId,
        version,
        current_version: 2,
        content: content(version === 1 ? "Original" : "Revised"),
        creator_type: "AI_SYSTEM",
      }), { headers: { "Content-Type": "application/json" } });
    }));
    const proposalMessage = (
      sequence: number,
      proposalVersion: number,
      state: "READY_FOR_DECISION" | "SUPERSEDED",
    ): AssistantMessage => ({
      id: `30000000-0000-4000-8000-${sequence.toString().padStart(12, "0")}`,
      sequence,
      role: "ASSISTANT",
      content_blocks: [{
        kind: "proposal",
        workflow_run_id: workflowRunId,
        proposal_id: proposalId,
        proposal_version: proposalVersion,
        state,
        read_only: state === "SUPERSEDED",
        current_version: state === "SUPERSEDED" ? 2 : null,
        error_codes: [],
      }],
      created_at: `2026-08-18T00:00:${sequence.toString().padStart(2, "0")}Z`,
    });

    const revisionRequest: AssistantMessage = {
      id: "30000000-0000-4000-8000-000000000099",
      sequence: 2,
      role: "USER",
      content_blocks: [{ kind: "text", text: "Extend the plan" }],
      created_at: "2026-08-18T00:00:02Z",
    };
    const { container } = renderWithAppProviders(<Transcript
      messages={[
        proposalMessage(1, 1, "READY_FOR_DECISION"),
        revisionRequest,
        proposalMessage(3, 1, "SUPERSEDED"),
        proposalMessage(4, 2, "READY_FOR_DECISION"),
      ]}
      canManage
      {...callbacks}
    />);

    expect(await screen.findAllByText("Proposal v1")).toHaveLength(1);
    expect(await screen.findAllByText("Proposal v2")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Original" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Revised" })).toBeVisible();
    expect(screen.getAllByText(/^Proposal v/)).toHaveLength(2);
    const transcript = container.querySelector(".assistant-transcript")?.textContent ?? "";
    expect(transcript.indexOf("Proposal v1")).toBeLessThan(transcript.indexOf("Extend the plan"));
    expect(transcript.indexOf("Extend the plan")).toBeLessThan(transcript.indexOf("Proposal v2"));
  });
});
