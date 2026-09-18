import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import type { RecommendationVersion } from "./contracts";
import { RecommendationCard } from "./recommendation-card";

const requirementId = "00000000-0000-4000-8000-000000000001";
const memberId = "00000000-0000-4000-8000-000000000002";

const recommendation: RecommendationVersion = {
  recommendation_id: "00000000-0000-4000-8000-000000000003",
  version: 1,
  requirement_set_id: "00000000-0000-4000-8000-000000000004",
  requirement_version: 2,
  policy_version: "ranking-v1",
  status: "PROPOSED",
  selections: [{ requirement_id: requirementId, membership_id: memberId, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
  alternatives: [{
    requirement_id: requirementId, membership_id: memberId, display_name: "Lan", eligible: true,
    hard_failure_codes: [], skill_points: "0.5000", capacity_points: "0.3000",
    evidence_points: "0.1500", familiarity_points: "0.0500", total_points: "1.0000",
    effective_capacity_hours: 40, residual_capacity_hours: 12,
    evidence: [{ id: "00000000-0000-4000-8000-000000000005", summary: "Delivered onboarding",
      source_resource_type: "task", source_resource_id: "00000000-0000-4000-8000-000000000006" }],
  }],
  uncovered: [{ requirement_id: requirementId, uncovered_effort_hours: "2" }],
  demands: [{ requirement_id: requirementId, project_week_id: "00000000-0000-4000-8000-000000000007", effort_hours: "10" }],
  diff: null,
  explanation_status: "UNAVAILABLE",
};

describe("RecommendationCard", () => {
  it("discloses deterministic score, evidence, workload and uncovered demand", () => {
    renderWithAppProviders(<RecommendationCard recommendation={recommendation} canManage onEdit={vi.fn()} onApprove={vi.fn()} onReject={vi.fn()} />);

    expect(screen.getByText("1 thành viên · 2 giờ chưa đáp ứng")).toBeVisible();
    fireEvent.click(screen.getByText("Điểm số, minh chứng và khối lượng"));
    expect(screen.getByText("Delivered onboarding")).toBeVisible();
    expect(screen.getByText("Còn lại 12 giờ")).toBeVisible();
    expect(screen.getByText("Kỹ năng")).toBeVisible();
    expect(screen.getByText("Không có giải thích AI; xếp hạng xác định vẫn khả dụng.")).toBeVisible();
  });

  it("keeps recommendation actions manager-only", () => {
    renderWithAppProviders(<RecommendationCard recommendation={recommendation} canManage={false} onEdit={vi.fn()} onApprove={vi.fn()} onReject={vi.fn()} />);

    expect(screen.getAllByText("Lan")[0]).toBeVisible();
    expect(screen.queryByRole("button", { name: "Đổi thành viên" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Phê duyệt đội ngũ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Từ chối đề xuất" })).not.toBeInTheDocument();
  });

  it("keeps scores scoped to each requirement when one member covers several requirements", () => {
    const secondRequirementId = "00000000-0000-4000-8000-000000000008";
    const secondCandidate = {
      ...recommendation.alternatives[0], requirement_id: secondRequirementId,
      total_points: "2.0000", skill_points: "0.9000",
    };
    const multiple = {
      ...recommendation,
      selections: [...recommendation.selections, {
        requirement_id: secondRequirementId, membership_id: memberId, allocated_effort_hours: "4",
        warning_codes: [], override_reason: null,
      }],
      alternatives: [...recommendation.alternatives, secondCandidate],
      demands: [...recommendation.demands, {
        requirement_id: secondRequirementId, project_week_id: "00000000-0000-4000-8000-000000000009", effort_hours: "4",
      }],
    } satisfies RecommendationVersion;

    renderWithAppProviders(<RecommendationCard recommendation={multiple} />);
    fireEvent.click(screen.getByText("Điểm số, minh chứng và khối lượng"));

    expect(screen.getByText("1.0000")).toBeVisible();
    expect(screen.getByText("2.0000")).toBeVisible();
  });
});
