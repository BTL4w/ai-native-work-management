import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { ActivityBlock } from "./activity-block";
import { UnavailableBlock } from "./unavailable-block";
import { WorkEvidenceBlock } from "./work-evidence-block";

describe("Assistant blocks", () => {
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
});
