import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";

import type { Member } from "@/features/work/contracts";

import type { ProposalContent } from "./contracts";

export function ProposalEditor({
  initial,
  members,
  saving,
  onCancel,
  onSave,
}: {
  initial: ProposalContent;
  members: Member[];
  saving: boolean;
  onCancel: () => void;
  onSave: (content: ProposalContent) => void;
}) {
  const t = useTranslations("ai");
  const [draft, setDraft] = useState(initial);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSave(draft);
  }

  function addMilestone() {
    const position = nextPosition(draft.milestones.map((item) => item.ref), "m");
    setDraft({ ...draft, milestones: [...draft.milestones, {
      ref: `m${position}`,
      title: `${t("milestones")} ${position}`,
      description: null,
      due_date: null,
    }] });
  }

  function addTask() {
    const position = nextPosition(draft.tasks.map((item) => item.ref), "t");
    setDraft({ ...draft, tasks: [...draft.tasks, {
      ref: `t${position}`,
      milestone_ref: draft.milestones[0]?.ref ?? null,
      title: `Task ${position}`,
      description: null,
      due_date: null,
      assignee_membership_id: null,
      acceptance_criteria: [],
    }] });
  }

  function addDependency() {
    if (draft.tasks.length < 2) return;
    const predecessor_ref = draft.tasks[0].ref;
    const successor_ref = draft.tasks[1].ref;
    if (draft.dependencies.some((item) => item.predecessor_ref === predecessor_ref && item.successor_ref === successor_ref)) return;
    setDraft({ ...draft, dependencies: [...draft.dependencies, { predecessor_ref, successor_ref }] });
  }

  function moveTask(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= draft.tasks.length) return;
    const tasks = [...draft.tasks];
    [tasks[index], tasks[target]] = [tasks[target], tasks[index]];
    setDraft({ ...draft, tasks });
  }

  function moveMilestone(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= draft.milestones.length) return;
    const milestones = [...draft.milestones];
    [milestones[index], milestones[target]] = [milestones[target], milestones[index]];
    setDraft({ ...draft, milestones });
  }

  function moveDependency(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= draft.dependencies.length) return;
    const dependencies = [...draft.dependencies];
    [dependencies[index], dependencies[target]] = [dependencies[target], dependencies[index]];
    setDraft({ ...draft, dependencies });
  }

  return (
    <form className="ai-card ai-editor" onSubmit={submit}>
      <h3>{t("editor.title")}</h3>
      <label>{t("editor.projectTitle")}<input value={draft.project.title} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, title: event.target.value } })} /></label>
      <label>{t("editor.projectDescription")}<textarea value={draft.project.description ?? ""} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, description: event.target.value || null } })} /></label>
      <label>{t("editor.startDate")}<input type="date" value={draft.project.start_date ?? ""} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, start_date: event.target.value || null } })} /></label>
      <label>{t("editor.projectDueDate")}<input type="date" value={draft.project.due_date ?? ""} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, due_date: event.target.value || null } })} /></label>
      <label>{t("editor.goalTitle")}<input value={draft.goal.title} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, title: event.target.value } })} /></label>
      <label>{t("editor.goalDescription")}<textarea value={draft.goal.description ?? ""} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, description: event.target.value || null } })} /></label>
      <label>{t("editor.expectedOutcomes")}<textarea value={draft.goal.expected_outcomes.join("\n")} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, expected_outcomes: lines(event.target.value) } })} /></label>
      <label>{t("editor.goalTargetDate")}<input type="date" value={draft.goal.target_date ?? ""} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, target_date: event.target.value || null } })} /></label>
      <fieldset><legend>{t("milestones")}</legend>
        {draft.milestones.map((milestone, index) => <div className="ai-editor-row" key={milestone.ref}>
          <label>{t("editor.milestoneTitle")}<input value={milestone.title} onChange={(event) => setDraft({ ...draft, milestones: draft.milestones.map((item, itemIndex) => itemIndex === index ? { ...item, title: event.target.value } : item) })} /></label>
          <label>{t("editor.description")}<textarea value={milestone.description ?? ""} onChange={(event) => setDraft({ ...draft, milestones: draft.milestones.map((item, itemIndex) => itemIndex === index ? { ...item, description: event.target.value || null } : item) })} /></label>
          <label>{t("editor.dueDate")}<input type="date" value={milestone.due_date ?? ""} onChange={(event) => setDraft({ ...draft, milestones: draft.milestones.map((item, itemIndex) => itemIndex === index ? { ...item, due_date: event.target.value || null } : item) })} /></label>
          <button aria-label={t("action.moveUp", { item: milestone.title })} disabled={index === 0} type="button" onClick={() => moveMilestone(index, -1)}>↑</button>
          <button aria-label={t("action.moveDown", { item: milestone.title })} disabled={index === draft.milestones.length - 1} type="button" onClick={() => moveMilestone(index, 1)}>↓</button>
          <button type="button" onClick={() => setDraft({ ...draft, milestones: draft.milestones.filter((_, itemIndex) => itemIndex !== index), tasks: draft.tasks.map((task) => task.milestone_ref === milestone.ref ? { ...task, milestone_ref: null } : task) })}>{t("action.remove")}</button>
        </div>)}
        <button type="button" onClick={addMilestone}>{t("action.addMilestone")}</button>
      </fieldset>
      <fieldset><legend>{t("tasks")}</legend>
        {draft.tasks.map((task, index) => (
          <div className="ai-editor-row" key={task.ref}>
            <label>{t("editor.taskTitle")}<input value={task.title} onChange={(event) => setDraft({ ...draft, tasks: draft.tasks.map((item, taskIndex) => taskIndex === index ? { ...item, title: event.target.value } : item) })} /></label>
            <label>{t("editor.description")}<textarea value={task.description ?? ""} onChange={(event) => setDraft({ ...draft, tasks: draft.tasks.map((item, taskIndex) => taskIndex === index ? { ...item, description: event.target.value || null } : item) })} /></label>
            <label>{t("editor.dueDate")}<input type="date" value={task.due_date ?? ""} onChange={(event) => setDraft({ ...draft, tasks: draft.tasks.map((item, taskIndex) => taskIndex === index ? { ...item, due_date: event.target.value || null } : item) })} /></label>
            <label>{t("editor.milestone")}<select value={task.milestone_ref ?? ""} onChange={(event) => setDraft({ ...draft, tasks: draft.tasks.map((item, taskIndex) => taskIndex === index ? { ...item, milestone_ref: event.target.value || null } : item) })}><option value="">{t("editor.unselected")}</option>{draft.milestones.map((milestone) => <option key={milestone.ref} value={milestone.ref}>{milestone.title}</option>)}</select></label>
            <label>{t("editor.assignee")}<select value={task.assignee_membership_id ?? ""} onChange={(event) => setDraft({ ...draft, tasks: draft.tasks.map((item, taskIndex) => taskIndex === index ? { ...item, assignee_membership_id: event.target.value || null } : item) })}>
              <option value="">{t("editor.unselected")}</option>
              {members.map((member) => <option key={member.membership_id} value={member.membership_id}>{member.display_name}</option>)}
            </select></label>
            <label>{t("editor.criteriaFor", { task: task.title })}<textarea aria-label={t("editor.criteriaFor", { task: task.title })} value={task.acceptance_criteria.join("\n")} onChange={(event) => setDraft({ ...draft, tasks: draft.tasks.map((item, taskIndex) => taskIndex === index ? { ...item, acceptance_criteria: lines(event.target.value) } : item) })} /></label>
            <button aria-label={t("action.moveUp", { item: task.title })} disabled={index === 0} type="button" onClick={() => moveTask(index, -1)}>↑</button>
            <button aria-label={t("action.moveDown", { item: task.title })} disabled={index === draft.tasks.length - 1} type="button" onClick={() => moveTask(index, 1)}>↓</button>
            <button type="button" onClick={() => setDraft({ ...draft, tasks: draft.tasks.filter((_, taskIndex) => taskIndex !== index), dependencies: draft.dependencies.filter((edge) => edge.predecessor_ref !== task.ref && edge.successor_ref !== task.ref) })}>{t("action.remove")}</button>
          </div>
        ))}
        <button type="button" onClick={addTask}>{t("action.addTask")}</button>
      </fieldset>
      <fieldset><legend>{t("dependencies")}</legend>{draft.dependencies.map((edge, index) => <div className="ai-editor-row" key={`${edge.predecessor_ref}-${edge.successor_ref}`}><label>{t("editor.predecessor")}<select value={edge.predecessor_ref} onChange={(event) => {
        const predecessor_ref = event.target.value;
        const successor_ref = edge.successor_ref === predecessor_ref ? draft.tasks.find((task) => task.ref !== predecessor_ref)?.ref ?? "" : edge.successor_ref;
        setDraft({ ...draft, dependencies: draft.dependencies.map((item, itemIndex) => itemIndex === index ? { ...item, predecessor_ref, successor_ref } : item) });
      }}>{draft.tasks.map((task) => <option key={task.ref} value={task.ref}>{task.title}</option>)}</select></label><label>{t("editor.successor")}<select value={edge.successor_ref} onChange={(event) => setDraft({ ...draft, dependencies: draft.dependencies.map((item, itemIndex) => itemIndex === index ? { ...item, successor_ref: event.target.value } : item) })}>{draft.tasks.filter((task) => task.ref !== edge.predecessor_ref).map((task) => <option key={task.ref} value={task.ref}>{task.title}</option>)}</select></label><button aria-label={t("action.moveUp", { item: `${edge.predecessor_ref} → ${edge.successor_ref}` })} disabled={index === 0} type="button" onClick={() => moveDependency(index, -1)}>↑</button><button aria-label={t("action.moveDown", { item: `${edge.predecessor_ref} → ${edge.successor_ref}` })} disabled={index === draft.dependencies.length - 1} type="button" onClick={() => moveDependency(index, 1)}>↓</button><button type="button" onClick={() => setDraft({ ...draft, dependencies: draft.dependencies.filter((_, itemIndex) => itemIndex !== index) })}>{t("action.remove")}</button></div>)}<button disabled={draft.tasks.length < 2} type="button" onClick={addDependency}>{t("action.addDependency")}</button></fieldset>
      <label>{t("editor.assumptions")}<textarea value={draft.assumptions.map((item) => item.description).join("\n")} onChange={(event) => setDraft({ ...draft, assumptions: lines(event.target.value).map((description) => ({ description, source: "manager_input" })) })} /></label>
      <div className="ai-actions"><button type="button" onClick={onCancel}>{t("action.cancel")}</button><button disabled={saving} type="submit">{saving ? t("action.saving") : t("action.save")}</button></div>
    </form>
  );
}

function nextPosition(refs: string[], prefix: string) {
  let position = 1;
  while (refs.includes(`${prefix}${position}`)) position += 1;
  return position;
}

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
