import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { CurrentTeam } from "./current-team";

describe("CurrentTeam", () => {
  it("shows active memberships and labels an unavailable member name explicitly", () => {
    renderWithAppProviders(<CurrentTeam memberNames={{}} team={{ memberships: [{
      id: "00000000-0000-4000-8000-000000000001",
      project_id: "00000000-0000-4000-8000-000000000002",
      membership_id: "00000000-0000-4000-8000-000000000003",
      decision_id: "00000000-0000-4000-8000-000000000004",
      active: true,
      created_at: "2026-09-19T00:00:00Z",
    }, {
      id: "00000000-0000-4000-8000-000000000005",
      project_id: "00000000-0000-4000-8000-000000000002",
      membership_id: "00000000-0000-4000-8000-000000000006",
      decision_id: "00000000-0000-4000-8000-000000000004",
      active: false,
      created_at: "2026-09-19T00:00:00Z",
    }] }} />);

    expect(screen.getByText("Tên thành viên chưa khả dụng")).toBeVisible();
    expect(screen.getByText("00000000-0000-4000-8000-000000000003")).toBeVisible();
    expect(screen.queryByText("00000000-0000-4000-8000-000000000006")).not.toBeInTheDocument();
    expect(screen.getByText("Không có task nào được giao từ quyết định đội ngũ này.")).toBeVisible();
  });
});
