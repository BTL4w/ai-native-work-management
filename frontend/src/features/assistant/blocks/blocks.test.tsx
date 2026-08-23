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
const detailedProposalContent = {
  project: { title: "Launch", description: "Ship the new experience", start_date: "2026-09-01", due_date: "2026-09-14" },
  goal: { title: "Ship safely", description: null, expected_outcomes: ["Customers can onboard"], target_date: "2026-09-14" },
  milestones: [{ ref: "m1", title: "Ready for release", description: null, due_date: "2026-09-07" }],
  project_weeks: [{ ref: "w1", week_number: 1, start_date: "2026-09-01", end_date: "2026-09-07", objective: "Prepare" }],
  tasks: [
    { ref: "t1", project_week_ref: "w1", milestone_ref: "m1", title: "Prepare launch", description: null, due_date: "2026-09-05", assignee_membership_id: null, required_skill_labels: ["communication"], estimated_effort_hours: 8, acceptance_criteria: ["Checklist ready"] },
    { ref: "t2", project_week_ref: "w1", milestone_ref: null, title: "Publish release", description: null, due_date: "2026-09-07", assignee_membership_id: null, required_skill_labels: [], estimated_effort_hours: 4, acceptance_criteria: ["Release is live"] },
  ],
  dependencies: [{ predecessor_ref: "t1", successor_ref: "t2" }],
  assumptions: [{ description: "The release date is fixed", source: "Manager request" }],
};

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

  it("shows the complete planning proposal inline before approval", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      proposal_id: proposalId,
      workflow_run_id: workflowRunId,
      version: 3,
      current_version: 3,
      content: detailedProposalContent,
      creator_type: "AI_SYSTEM",
    }), { headers: { "Content-Type": "application/json" } })));

    renderWithAppProviders(<PlanningBlock
      block={{
        kind: "proposal",
        workflow_run_id: workflowRunId,
        proposal_id: proposalId,
        proposal_version: 3,
        approval_id: "33333333-3333-4333-8333-333333333333",
        can_approve: true,
        read_only: false,
        current_version: 3,
        error_codes: [],
      }}
      canManage
      onEdit={vi.fn()}
      onRevise={vi.fn()}
      onApprove={vi.fn()}
      onReject={vi.fn()}
    />);

    expect(await screen.findByRole("heading", { name: "Launch" })).toBeVisible();
    expect(screen.getByText("Mục tiêu")).toBeVisible();
    expect(screen.getByText("Tuần 1")).toBeVisible();
    expect(screen.getByText("Checklist ready")).toBeVisible();
    expect(screen.getByText("Prepare launch → Publish release")).toBeVisible();
    expect(screen.getByText("Đã kiểm tra thời hạn, dependency và dữ liệu bắt buộc")).toBeVisible();
    expect(screen.getByRole("button", { name: "Phê duyệt kế hoạch" })).toBeEnabled();
  });

  it("does not present a non-approvable proposal as validation-ready", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      proposal_id: proposalId,
      workflow_run_id: workflowRunId,
      version: 4,
      current_version: 4,
      content: detailedProposalContent,
      creator_type: "AI_SYSTEM",
    }), { headers: { "Content-Type": "application/json" } })));

    renderWithAppProviders(<PlanningBlock
      block={{
        kind: "proposal",
        workflow_run_id: workflowRunId,
        proposal_id: proposalId,
        proposal_version: 4,
        approval_id: "33333333-3333-4333-8333-333333333333",
        can_approve: false,
        read_only: false,
        current_version: 4,
        error_codes: [],
      }}
      canManage
      onEdit={vi.fn()}
      onRevise={vi.fn()}
      onApprove={vi.fn()}
      onReject={vi.fn()}
    />);

    expect(await screen.findByText("Proposal chưa vượt qua deterministic validation.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Phê duyệt kế hoạch" })).toBeDisabled();
    expect(screen.queryByText("Đã kiểm tra thời hạn, dependency và dữ liệu bắt buộc")).not.toBeInTheDocument();
  });
});
