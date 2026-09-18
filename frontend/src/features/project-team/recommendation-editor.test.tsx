import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import type { RecommendationVersion } from "./contracts";
import { RecommendationEditor } from "./recommendation-editor";

const req1 = "00000000-0000-4000-8000-000000000001";
const req2 = "00000000-0000-4000-8000-000000000002";
const lan = "00000000-0000-4000-8000-000000000003";
const minh = "00000000-0000-4000-8000-000000000004";
const week = "00000000-0000-4000-8000-000000000005";

describe("RecommendationEditor", () => {
  it("can fill an uncovered requirement in the next immutable version", () => {
    const onSave = vi.fn();
    renderWithAppProviders(<RecommendationEditor recommendation={recommendation()} submitting={false} onCancel={vi.fn()} onSave={onSave} />);

    expect(screen.getAllByLabelText("Thành viên")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 2" }));
    expect(onSave).toHaveBeenCalledWith([
      { requirement_id: req1, selected_membership_id: lan, override_reason: null, allocated_effort_hours: "8" },
      { requirement_id: req2, selected_membership_id: minh, override_reason: null, allocated_effort_hours: "4" },
    ]);
  });

  it("materializes a null pending allocation from the requirement demand", () => {
    const onSave = vi.fn();
    renderWithAppProviders(<RecommendationEditor recommendation={recommendation()} initialOverrides={[{
      requirement_id: req1,
      selected_membership_id: lan,
      override_reason: null,
      allocated_effort_hours: null,
    }]} submitting={false} onCancel={vi.fn()} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Lưu thành phiên bản 2" }));

    expect(onSave).toHaveBeenCalledWith(expect.arrayContaining([
      expect.objectContaining({ requirement_id: req1, allocated_effort_hours: "8" }),
    ]));
  });
});

function recommendation(): RecommendationVersion {
  const candidate = (requirementId: string, membershipId: string, displayName: string) => ({
    requirement_id: requirementId, membership_id: membershipId, display_name: displayName, eligible: true,
    hard_failure_codes: [], skill_points: "0.5000", capacity_points: "0.3000", evidence_points: "0.1000",
    familiarity_points: "0.0500", total_points: "0.9500", effective_capacity_hours: 40,
    residual_capacity_hours: 20, evidence: [],
  });
  return {
    recommendation_id: "00000000-0000-4000-8000-000000000006", version: 1,
    requirement_set_id: "00000000-0000-4000-8000-000000000007", requirement_version: 1,
    policy_version: "ranking-v1", status: "PROPOSED",
    selections: [{ requirement_id: req1, membership_id: lan, allocated_effort_hours: "8", warning_codes: [], override_reason: null }],
    alternatives: [candidate(req1, lan, "Lan"), candidate(req2, minh, "Minh")],
    uncovered: [{ requirement_id: req2, uncovered_effort_hours: "4" }],
    demands: [{ requirement_id: req1, project_week_id: week, effort_hours: "8" }, { requirement_id: req2, project_week_id: week, effort_hours: "4" }],
    diff: null, explanation_status: "NOT_REQUESTED",
  };
}
