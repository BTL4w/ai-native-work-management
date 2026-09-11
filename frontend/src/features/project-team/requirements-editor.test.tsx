import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithAppProviders } from "@/test/render";

import { RequirementsEditor } from "./requirements-editor";

const item = { id: "00000000-0000-4000-8000-000000000001", skill_id: "00000000-0000-4000-8000-000000000002",
  minimum_level: 3, project_week_id: "00000000-0000-4000-8000-000000000003", effort_hours: 8, source_task_ids: [] };

describe("RequirementsEditor", () => {
  it("shows inline validation and blocks saving duplicate skill/week rows", () => {
    const save = vi.fn();
    renderWithAppProviders(<RequirementsEditor items={[item, { ...item, id: "00000000-0000-4000-8000-000000000004" }]}
      skills={[{ id: item.skill_id, name: "Analysis" }]} weeks={[{ id: item.project_week_id, label: "Tuần 1" }]}
      tasks={[]} onCancel={() => undefined} onSave={save} submitting={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Lưu yêu cầu" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Mỗi kỹ năng chỉ được xuất hiện một lần trong cùng tuần.");
    expect(save).not.toHaveBeenCalled();
  });

  it("allows effort and minimum level edits", () => {
    const save = vi.fn();
    renderWithAppProviders(<RequirementsEditor items={[item]} skills={[{ id: item.skill_id, name: "Analysis" }]}
      weeks={[{ id: item.project_week_id, label: "Tuần 1" }]} tasks={[]} onCancel={() => undefined} onSave={save} submitting={false} />);
    fireEvent.change(screen.getByLabelText("Mức tối thiểu"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Số giờ cần"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu yêu cầu" }));
    expect(save).toHaveBeenCalledWith([expect.objectContaining({ minimum_level: 4, effort_hours: 12 })]);
  });
});
