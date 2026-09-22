import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { ActivityBlock } from "./activity-block";
import { PlanningBlock } from "./planning-block";
import { TeamRecommendationBlock } from "./team-recommendation-block";
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
    const week = screen.getByRole("button", { name: /Tuần 1.*Prepare.*2026-09-01.*2026-09-07/ });
    expect(week).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Prepare launch")).not.toBeInTheDocument();
    expect(screen.queryByText("Checklist ready")).not.toBeInTheDocument();
    expect(screen.getByText("Prepare launch → Publish release")).toBeVisible();

    fireEvent.click(week);
    expect(week).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Prepare launch")).toBeVisible();
    expect(screen.getByText("Checklist ready")).toBeVisible();

    fireEvent.click(week);
    expect(week).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Prepare launch")).not.toBeInTheDocument();
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

  it("shows an immutable team diff with expandable evidence and workload", async () => {
    const recommendationId = "44444444-4444-4444-8444-444444444444";
    const requirementId = "55555555-5555-4555-8555-555555555555";
    const oldMemberId = "66666666-6666-4666-8666-666666666666";
    const newMemberId = "77777777-7777-4777-8777-777777777777";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      recommendation_id: recommendationId,
      version: 2,
      requirement_set_id: "88888888-8888-4888-8888-888888888888",
      requirement_version: 1,
      policy_version: "ranking-v1",
      status: "PROPOSED",
      selections: [{ requirement_id: requirementId, membership_id: newMemberId, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
      alternatives: [
        { requirement_id: requirementId, membership_id: oldMemberId, display_name: "Lan", eligible: true, hard_failure_codes: [], skill_points: "0.5", capacity_points: "0.3", evidence_points: "0.1", familiarity_points: "0.1", total_points: "1.0", effective_capacity_hours: 40, residual_capacity_hours: 20, evidence: [] },
        { requirement_id: requirementId, membership_id: newMemberId, display_name: "Minh", eligible: true, hard_failure_codes: [], skill_points: "0.5", capacity_points: "0.3", evidence_points: "0.1", familiarity_points: "0.1", total_points: "1.0", effective_capacity_hours: 40, residual_capacity_hours: 12, evidence: [{ id: "99999999-9999-4999-8999-999999999999", summary: "Delivered onboarding", source_resource_type: "task", source_resource_id: proposalId }] },
      ],
      uncovered: [],
      demands: [{ requirement_id: requirementId, project_week_id: workflowRunId, effort_hours: "8" }],
      diff: {
        added_membership_ids: [newMemberId],
        removed_membership_ids: [oldMemberId],
        before: [{ requirement_id: requirementId, membership_id: oldMemberId, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
        after: [{ requirement_id: requirementId, membership_id: newMemberId, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
      },
      explanation_status: "UNAVAILABLE",
    }), { headers: { "Content-Type": "application/json" } })));

    renderWithAppProviders(<TeamRecommendationBlock
      block={{ kind: "team_recommendation", project_id: proposalId, recommendation_id: recommendationId, recommendation_version: 2, status: "PROPOSED", explanation_status: "UNAVAILABLE" }}
      canManage
      isLatest={false}
      onRequestRevision={vi.fn()}
      onManualRevise={vi.fn()}
      onDecide={vi.fn()}
    />);

    expect(await screen.findByText("Đề xuất v2 chỉ đọc vì đã có phiên bản mới hơn.")).toBeVisible();
    expect(screen.getByText("Lan → Minh")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Yêu cầu chỉnh đội" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Điểm số, minh chứng và khối lượng"));
    expect(screen.getByText("Delivered onboarding")).toBeVisible();
    expect(screen.getByText("Còn lại 12 giờ")).toBeVisible();
    expect(screen.getByText("Không có giải thích AI; xếp hạng xác định vẫn khả dụng.")).toBeVisible();
  });

  it("offers the manual Team path when an inline recommendation cannot load", async () => {
    const onOpenTeam = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: {
      code: "MODEL_UNAVAILABLE", message_key: "assistant.error.safe", request_id: "request-1", field_errors: [], details: {},
    } }), { status: 503, headers: { "Content-Type": "application/json" } })));

    renderWithAppProviders(<TeamRecommendationBlock
      block={{ kind: "team_recommendation", project_id: proposalId, recommendation_id: "44444444-4444-4444-8444-444444444444", recommendation_version: 1, status: "PROPOSED", explanation_status: "UNAVAILABLE" }}
      canManage
      isLatest
      onRequestRevision={vi.fn()}
      onManualRevise={vi.fn()}
      onDecide={vi.fn()}
      onOpenTeam={onOpenTeam}
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Mở tab Đội ngũ" }));
    expect(onOpenTeam).toHaveBeenCalledWith(proposalId);
  });

  it("states the zero-assignment boundary before an inline team approval", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      recommendation_id: "44444444-4444-4444-8444-444444444444", version: 1,
      requirement_set_id: "55555555-5555-4555-8555-555555555555", requirement_version: 1,
      policy_version: "ranking-v1", status: "PROPOSED", selections: [], alternatives: [], uncovered: [], demands: [], diff: null,
      explanation_status: "AVAILABLE",
    }), { headers: { "Content-Type": "application/json" } })));

    renderWithAppProviders(<TeamRecommendationBlock
      block={{ kind: "team_recommendation", project_id: proposalId, recommendation_id: "44444444-4444-4444-8444-444444444444", recommendation_version: 1, status: "PROPOSED", explanation_status: "AVAILABLE" }}
      canManage
      isLatest
      onRequestRevision={vi.fn()}
      onManualRevise={vi.fn()}
      onDecide={vi.fn()}
    />);

    fireEvent.click(await screen.findByRole("button", { name: "Phê duyệt đội ngũ" }));
    expect(screen.getByText("Phê duyệt chỉ thêm thành viên Project Team và không giao Task.")).toBeVisible();
  });
});
