import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { ActivityBlock } from "./activity-block";
import { PlanningBlock } from "./planning-block";
import { UnavailableBlock } from "./unavailable-block";
import { WorkEvidenceBlock } from "./work-evidence-block";

const proposalId = "11111111-1111-4111-8111-111111111111";
const workflowRunId = "22222222-2222-4222-8222-222222222222";
const proposalContent = (title: string) => ({
  project: { title, description: null, start_date: null, due_date: null },
  goal: { title, description: null, expected_outcomes: [], target_date: null },
  milestones: [],
  project_weeks: [],
  tasks: [],
  dependencies: [],
  assumptions: [],
});

describe("Assistant blocks", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("expands only safe activity details", () => {
    renderWithAppProviders(<ActivityBlock block={{
      kind: "activity",
      label_key: "assistant.activity.planning",
      status: "RUNNING",
      agent_id: "planning",
    }} />);

    expect(screen.queryByText("planning")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Xem chi tiết hoạt động" }));
    expect(screen.getByText("planning")).toBeVisible();
    expect(document.body.textContent).not.toContain("prompt");
    expect(document.body.textContent).not.toContain("reasoning");
  });

  it("shows Work evidence without mutation controls", () => {
    renderWithAppProviders(<WorkEvidenceBlock block={{
      kind: "work_evidence",
      summary: "Hai task đang bị chặn.",
      evidence: [{
        evidence_id: "task-1",
        resource_type: "task",
        resource_id: "11111111-1111-4111-8111-111111111111",
        version: 2,
      }],
    }} />);

    expect(screen.getByText("Hai task đang bị chặn.")).toBeVisible();
    expect(screen.getByText("task · v2")).toBeVisible();
    expect(screen.queryByRole("button", { name: /phê duyệt|chỉnh|giao/i })).not.toBeInTheDocument();
  });

  it("makes an unavailable later-phase capability explicit", () => {
    renderWithAppProviders(<UnavailableBlock block={{
      kind: "capability_unavailable",
      capability: "daily_update",
      message_key: "assistant.unavailable.dailyUpdate",
    }} />);

    expect(screen.getByRole("status")).toHaveTextContent("Daily Update chưa khả dụng trong phase hiện tại");
  });

  it("keeps historical proposal cards bound to their immutable versions", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const version = path.endsWith("/versions/1") ? 1 : 2;
      return new Response(JSON.stringify({
        proposal_id: proposalId,
        workflow_run_id: workflowRunId,
        version,
        current_version: 2,
        content: proposalContent(version === 1 ? "Original proposal" : "Revised proposal"),
        creator_type: "AI_SYSTEM",
      }), { headers: { "Content-Type": "application/json" } });
    }));
    const callbacks = {
      onEdit: vi.fn(),
      onRevise: vi.fn(),
      onApprove: vi.fn(),
      onReject: vi.fn(),
    };

    renderWithAppProviders(<>
      <PlanningBlock
        block={{
          kind: "proposal",
          workflow_run_id: workflowRunId,
          proposal_id: proposalId,
          proposal_version: 1,
          read_only: false,
          error_codes: [],
        }}
        canManage
        {...callbacks}
      />
      <PlanningBlock
        block={{
          kind: "proposal",
          workflow_run_id: workflowRunId,
          proposal_id: proposalId,
          proposal_version: 2,
          read_only: false,
          current_version: 2,
          error_codes: [],
        }}
        canManage
        {...callbacks}
      />
    </>);

    expect(await screen.findByRole("heading", { name: "Original proposal" })).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Revised proposal" })).toBeVisible();
    expect(screen.getByText("Proposal v1")).toBeVisible();
    expect(screen.getByText("Proposal v2")).toBeVisible();
    expect(screen.getByText("Card này chỉ đọc. Version hiện tại là v2.")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Nhờ AI chỉnh" })).toHaveLength(1);
  });
});
