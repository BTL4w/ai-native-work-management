import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { RankingPreviewView } from "./ranking-preview";

const req = "00000000-0000-4000-8000-000000000001";
const preview = { requirement_set_id: "00000000-0000-4000-8000-000000000002", requirement_version: 1,
  policy_version: "ranking-v1" as const, origin: "DETERMINISTIC" as const, candidates: [{ requirement_id: req,
    membership_id: "00000000-0000-4000-8000-000000000003", display_name: "Lan", eligible: true,
    hard_failure_codes: [], skill_points: "0.5000", capacity_points: "0.3000", evidence_points: "0.1500",
    familiarity_points: "0.0500", total_points: "1.0000", effective_capacity_hours: null,
    residual_capacity_hours: null, evidence: [{ id: "00000000-0000-4000-8000-000000000004", summary: "Completed discovery",
      source_resource_type: "task", source_resource_id: "00000000-0000-4000-8000-000000000005" }] }], allocations: [],
  uncovered: [{ requirement_id: req, uncovered_effort_hours: "3" }] };

describe("RankingPreviewView", () => {
  it("explains every deterministic component, unknown capacity, evidence and uncovered demand", () => {
    const openTask = vi.fn();
    const { container } = renderWithAppProviders(<RankingPreviewView preview={preview} requirementLabels={{ [req]: "Analysis · Tuần 1" }} onOpenEvidenceTask={openTask} openableEvidenceTaskIds={new Set(["00000000-0000-4000-8000-000000000005"])} />);
    expect(screen.getByText("ranking-v1")).toBeVisible();
    expect(screen.getByText("Kỹ năng")).toBeVisible();
    expect(screen.getByText("Năng lực còn lại")).toBeVisible();
    expect(screen.getByText("Minh chứng")).toBeVisible();
    expect(screen.getByText("Mức độ quen thuộc")).toBeVisible();
    expect(screen.getByText("Chưa có dữ liệu năng lực")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Completed discovery" }));
    expect(openTask).toHaveBeenCalledWith("00000000-0000-4000-8000-000000000005");
    expect(screen.getByText(/3 giờ chưa được đáp ứng/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /phê duyệt|thay đổi/i })).not.toBeInTheDocument();
    expect(container.querySelector("dl")?.className).toContain("sm:grid-cols-4");
  });

  it("renders the ranking explanation in English", () => {
    renderWithAppProviders(<RankingPreviewView preview={preview} requirementLabels={{ [req]: "Analysis · Week 1" }} />, "en");
    expect(screen.getByText("Candidate ranking")).toBeVisible();
    expect(screen.getByText("Residual capacity")).toBeVisible();
    expect(screen.getByText("Capacity data unavailable")).toBeVisible();
  });

  it("does not offer broken navigation for evidence outside the current Project", () => {
    renderWithAppProviders(<RankingPreviewView preview={preview} requirementLabels={{ [req]: "Analysis" }} onOpenEvidenceTask={vi.fn()} openableEvidenceTaskIds={new Set()} />);
    expect(screen.getByText("Completed discovery")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Completed discovery" })).not.toBeInTheDocument();
  });
});
