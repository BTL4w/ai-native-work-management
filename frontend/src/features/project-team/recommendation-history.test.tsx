import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import type { RecommendationVersion } from "./contracts";
import { RecommendationHistory } from "./recommendation-history";

const lan = "00000000-0000-4000-8000-000000000001";
const minh = "00000000-0000-4000-8000-000000000002";
const requirement = "00000000-0000-4000-8000-000000000003";

describe("RecommendationHistory", () => {
  it("shows the immutable previous selection together with the v1 to v2 diff", () => {
    const v1 = version(1, lan, "Lan", null);
    const v2 = version(2, minh, "Minh", {
      added_membership_ids: [minh], removed_membership_ids: [lan], before: v1.selections,
      after: [{ requirement_id: requirement, membership_id: minh, allocated_effort_hours: "8", warning_codes: [], override_reason: "Availability" }],
    });
    renderWithAppProviders(<RecommendationHistory current={v2} previous={[v1]} />);

    const history = screen.getByRole("region", { name: "Lịch sử bất biến" });
    expect(within(history).getByText("Lan → Minh")).toBeVisible();
    expect(within(history).getByText("Phiên bản 1 · chỉ đọc")).toBeVisible();
    expect(within(history).getByText("Thành viên: Lan")).toBeVisible();
  });

  it("describes an allocation-only revision without claiming a member was removed", () => {
    const v1 = version(1, lan, "Lan", null);
    const v2 = version(2, lan, "Lan", {
      added_membership_ids: [], removed_membership_ids: [], before: v1.selections,
      after: [{ ...v1.selections[0], allocated_effort_hours: "6", override_reason: "Adjusted allocation" }],
    });

    renderWithAppProviders(<RecommendationHistory current={v2} previous={[v1]} />);

    expect(screen.getByText("Thành viên không đổi; phân bổ hoặc lý do đã được cập nhật.")).toBeVisible();
  });
});

function version(number: number, membershipId: string, displayName: string, diff: RecommendationVersion["diff"]): RecommendationVersion {
  return {
    recommendation_id: "00000000-0000-4000-8000-000000000004", version: number,
    requirement_set_id: "00000000-0000-4000-8000-000000000005", requirement_version: 1,
    policy_version: "ranking-v1", status: "PROPOSED",
    selections: [{ requirement_id: requirement, membership_id: membershipId, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
    alternatives: [{ requirement_id: requirement, membership_id: membershipId, display_name: displayName, eligible: true,
      hard_failure_codes: [], skill_points: "0.5", capacity_points: "0.3", evidence_points: "0.1",
      familiarity_points: "0.05", total_points: "0.95", effective_capacity_hours: 40,
      residual_capacity_hours: 20, evidence: [] }],
    uncovered: [], demands: [{ requirement_id: requirement, project_week_id: "00000000-0000-4000-8000-000000000006", effort_hours: "8" }],
    diff, explanation_status: "NOT_REQUESTED",
  };
}
