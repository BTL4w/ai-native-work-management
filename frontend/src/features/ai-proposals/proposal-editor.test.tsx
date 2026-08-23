import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppLocaleProvider } from "@/shared/i18n/locale-provider";

import { ProposalEditor } from "./proposal-editor";

const initial = {
  project: { title: "Conference", description: null, start_date: null, due_date: null },
  goal: { title: "Engage customers", description: null, expected_outcomes: [], target_date: null },
  milestones: [],
  project_weeks: [{ ref: "w1", week_number: 1, start_date: "2026-08-17", end_date: "2026-08-23", objective: "Prepare" }],
  tasks: [],
  dependencies: [],
  assumptions: [],
};

describe("ProposalEditor", () => {
  it("adds structured milestones, tasks, criteria and dependencies", () => {
    const onSave = vi.fn();
    render(
      <AppLocaleProvider initialLocale="vi">
        <ProposalEditor initial={initial} saving={false} onCancel={vi.fn()} onSave={onSave} />
      </AppLocaleProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Thêm milestone" }));
    fireEvent.click(screen.getByRole("button", { name: /Tuần 1.*Prepare/ }));
    fireEvent.click(screen.getByRole("button", { name: "Thêm task" }));
    fireEvent.click(screen.getByRole("button", { name: "Thêm task" }));
    fireEvent.change(screen.getByLabelText("Tiêu chí chấp nhận của Task 1"), {
      target: { value: "Venue comparison completed" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Thêm dependency" }));
    fireEvent.click(screen.getByRole("button", { name: "Lưu version mới" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      milestones: expect.arrayContaining([expect.objectContaining({ ref: "m1" })]),
      tasks: expect.arrayContaining([expect.objectContaining({
        ref: "t1",
        acceptance_criteria: ["Venue comparison completed"],
      })]),
      dependencies: expect.arrayContaining([expect.objectContaining({ predecessor_ref: "t1", successor_ref: "t2" })]),
    }));
  });

  it("reorders tasks and prevents an obvious self-dependency", () => {
    const onSave = vi.fn();
    render(
      <AppLocaleProvider initialLocale="vi">
        <ProposalEditor
          initial={{
            ...initial,
            tasks: [
              { ref: "t1", project_week_ref: "w1", milestone_ref: null, title: "First", description: null, due_date: null, assignee_membership_id: null, required_skill_labels: [], estimated_effort_hours: 1, acceptance_criteria: [] },
              { ref: "t2", project_week_ref: "w1", milestone_ref: null, title: "Second", description: null, due_date: null, assignee_membership_id: null, required_skill_labels: [], estimated_effort_hours: 1, acceptance_criteria: [] },
            ],
          }}
          saving={false}
          onCancel={vi.fn()}
          onSave={onSave}
        />
      </AppLocaleProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Tuần 1.*Prepare/ }));
    fireEvent.click(screen.getByRole("button", { name: "Đưa Second lên" }));
    fireEvent.click(screen.getByRole("button", { name: "Thêm dependency" }));

    const successor = screen.getByLabelText("Task sau");
    expect(successor).not.toHaveTextContent("Second");
    fireEvent.click(screen.getByRole("button", { name: "Lưu version mới" }));
    expect(onSave.mock.calls[0][0].tasks.map((task: { ref: string }) => task.ref)).toEqual(["t2", "t1"]);
  });
});
