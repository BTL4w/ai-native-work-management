import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import type { ProposalContent } from "./contracts";

export function ProposalEditor({ initial, saving, onCancel, onSave }: {
  initial: ProposalContent;
  saving: boolean;
  onCancel: () => void;
  onSave: (content: ProposalContent) => void;
}) {
  const t = useTranslations("ai");
  const [draft, setDraft] = useState(initial);
  const [expandedWeeks, setExpandedWeeks] = useState<Set<string>>(() => new Set());

  function submit(event: FormEvent) {
    event.preventDefault();
    onSave(draft);
  }

  function toggleWeek(ref: string) {
    setExpandedWeeks((current) => {
      const next = new Set(current);
      if (next.has(ref)) next.delete(ref);
      else next.add(ref);
      return next;
    });
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

  function addTask(projectWeekRef = draft.project_weeks[0]?.ref) {
    if (!projectWeekRef) return;
    const position = nextPosition(draft.tasks.map((item) => item.ref), "t");
    setDraft({ ...draft, tasks: [...draft.tasks, {
      ref: `t${position}`,
      project_week_ref: projectWeekRef,
      milestone_ref: draft.milestones[0]?.ref ?? null,
      title: `Task ${position}`,
      description: null,
      due_date: null,
      assignee_membership_id: null,
      required_skill_labels: [],
      estimated_effort_hours: 1,
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
    <form className="ai-card ai-proposal-card ai-editor ai-inline-editor" onSubmit={submit}>
      <header className="ai-proposal-title ai-inline-project">
        <EditorField label={t("editor.projectTitle")}><input value={draft.project.title} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, title: event.target.value } })} /></EditorField>
        <EditorField label={t("editor.projectDescription")}><textarea rows={2} value={draft.project.description ?? ""} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, description: event.target.value || null } })} /></EditorField>
        <div className="ai-inline-field-grid">
          <EditorField label={t("editor.startDate")}><input type="date" value={draft.project.start_date ?? ""} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, start_date: event.target.value || null } })} /></EditorField>
          <EditorField label={t("editor.projectDueDate")}><input type="date" value={draft.project.due_date ?? ""} onChange={(event) => setDraft({ ...draft, project: { ...draft.project, due_date: event.target.value || null } })} /></EditorField>
        </div>
      </header>

      <EditorSection title={t("goal")}>
        <EditorField label={t("editor.goalTitle")}><input value={draft.goal.title} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, title: event.target.value } })} /></EditorField>
        <EditorField label={t("editor.goalDescription")}><textarea rows={2} value={draft.goal.description ?? ""} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, description: event.target.value || null } })} /></EditorField>
        <div className="ai-inline-field-grid">
          <EditorField label={t("editor.expectedOutcomes")}><textarea rows={3} value={draft.goal.expected_outcomes.join("\n")} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, expected_outcomes: lines(event.target.value) } })} /></EditorField>
          <EditorField label={t("editor.goalTargetDate")}><input type="date" value={draft.goal.target_date ?? ""} onChange={(event) => setDraft({ ...draft, goal: { ...draft.goal, target_date: event.target.value || null } })} /></EditorField>
        </div>
      </EditorSection>

      <EditorSection title={t("editor.assumptions")}>
        <EditorField label={t("editor.assumptions")} visuallyHidden><textarea rows={3} value={draft.assumptions.map((item) => item.description).join("\n")} onChange={(event) => setDraft({ ...draft, assumptions: lines(event.target.value).map((description) => ({ description, source: "manager_input" })) })} /></EditorField>
      </EditorSection>

      <EditorSection title={t("milestones")}>
        <div className="ai-inline-collection">
          {draft.milestones.map((milestone, index) => <article className="ai-inline-item" key={milestone.ref}>
            <div className="ai-inline-item-fields">
              <EditorField label={t("editor.milestoneTitle")}><input value={milestone.title} onChange={(event) => setDraft({ ...draft, milestones: draft.milestones.map((item, itemIndex) => itemIndex === index ? { ...item, title: event.target.value } : item) })} /></EditorField>
              <EditorField label={t("editor.description")}><textarea rows={2} value={milestone.description ?? ""} onChange={(event) => setDraft({ ...draft, milestones: draft.milestones.map((item, itemIndex) => itemIndex === index ? { ...item, description: event.target.value || null } : item) })} /></EditorField>
              <EditorField label={t("editor.dueDate")}><input type="date" value={milestone.due_date ?? ""} onChange={(event) => setDraft({ ...draft, milestones: draft.milestones.map((item, itemIndex) => itemIndex === index ? { ...item, due_date: event.target.value || null } : item) })} /></EditorField>
            </div>
            <ItemActions title={milestone.title} first={index === 0} last={index === draft.milestones.length - 1} onMove={(offset) => moveMilestone(index, offset)} onRemove={() => setDraft({ ...draft, milestones: draft.milestones.filter((_, itemIndex) => itemIndex !== index), tasks: draft.tasks.map((task) => task.milestone_ref === milestone.ref ? { ...task, milestone_ref: null } : task) })} />
          </article>)}
        </div>
        <button aria-label={t("action.addMilestone")} className="ai-inline-add" type="button" onClick={addMilestone}>＋ {t("action.addMilestone")}</button>
      </EditorSection>

      <EditorSection className="ai-proposal-timeline" title={t("projectWeeks")}>
        {draft.project_weeks.toSorted((a, b) => a.week_number - b.week_number).map((week) => {
          const expanded = expandedWeeks.has(week.ref);
          const contentId = `edit-week-${week.ref}`;
          return <section className={`ai-proposal-week ai-inline-week ${expanded ? "is-expanded" : ""}`} key={week.ref}>
            <button aria-controls={contentId} aria-expanded={expanded} className="ai-proposal-week-heading" type="button" onClick={() => toggleWeek(week.ref)}>
              <span className="ai-proposal-week-summary"><span className="ai-proposal-week-number">{t("editor.weekNumber", { number: week.week_number })}</span><span className="ai-proposal-week-objective">{week.objective}</span></span>
              <span className="ai-proposal-week-meta"><time>{week.start_date} → {week.end_date}</time><Chevron /></span>
            </button>
            {expanded ? <div className="ai-inline-week-content" id={contentId}>
              <div className="ai-inline-week-fields">
                <EditorField label={t("editor.weekObjective")}><input value={week.objective} onChange={(event) => setDraft({ ...draft, project_weeks: draft.project_weeks.map((item) => item.ref === week.ref ? { ...item, objective: event.target.value } : item) })} /></EditorField>
                <EditorField label={t("editor.startDate")}><input type="date" value={week.start_date} onChange={(event) => setDraft({ ...draft, project_weeks: draft.project_weeks.map((item) => item.ref === week.ref ? { ...item, start_date: event.target.value } : item) })} /></EditorField>
                <EditorField label={t("editor.dueDate")}><input type="date" value={week.end_date} onChange={(event) => setDraft({ ...draft, project_weeks: draft.project_weeks.map((item) => item.ref === week.ref ? { ...item, end_date: event.target.value } : item) })} /></EditorField>
              </div>
              <div className="ai-inline-task-list">
                {draft.tasks.map((task, index) => task.project_week_ref === week.ref ? <TaskEditor key={task.ref} task={task} index={index} draft={draft} setDraft={setDraft} moveTask={moveTask} /> : null)}
              </div>
              <button aria-label={t("action.addTask")} className="ai-inline-add" type="button" onClick={() => addTask(week.ref)}>＋ {t("action.addTask")}</button>
            </div> : null}
          </section>;
        })}
      </EditorSection>

      <EditorSection title={t("dependencies")}>
        <div className="ai-inline-collection">
          {draft.dependencies.map((edge, index) => <article className="ai-inline-item ai-inline-dependency" key={`${edge.predecessor_ref}-${edge.successor_ref}`}>
            <div className="ai-inline-item-fields">
              <EditorField label={t("editor.predecessor")}><select value={edge.predecessor_ref} onChange={(event) => {
                const predecessor_ref = event.target.value;
                const successor_ref = edge.successor_ref === predecessor_ref ? draft.tasks.find((task) => task.ref !== predecessor_ref)?.ref ?? "" : edge.successor_ref;
                setDraft({ ...draft, dependencies: draft.dependencies.map((item, itemIndex) => itemIndex === index ? { ...item, predecessor_ref, successor_ref } : item) });
              }}>{draft.tasks.map((task) => <option key={task.ref} value={task.ref}>{task.title}</option>)}</select></EditorField>
              <EditorField label={t("editor.successor")}><select value={edge.successor_ref} onChange={(event) => setDraft({ ...draft, dependencies: draft.dependencies.map((item, itemIndex) => itemIndex === index ? { ...item, successor_ref: event.target.value } : item) })}>{draft.tasks.filter((task) => task.ref !== edge.predecessor_ref).map((task) => <option key={task.ref} value={task.ref}>{task.title}</option>)}</select></EditorField>
            </div>
            <ItemActions title={`${edge.predecessor_ref} → ${edge.successor_ref}`} first={index === 0} last={index === draft.dependencies.length - 1} onMove={(offset) => moveDependency(index, offset)} onRemove={() => setDraft({ ...draft, dependencies: draft.dependencies.filter((_, itemIndex) => itemIndex !== index) })} />
          </article>)}
        </div>
        <button aria-label={t("action.addDependency")} className="ai-inline-add" disabled={draft.tasks.length < 2} type="button" onClick={addDependency}>＋ {t("action.addDependency")}</button>
      </EditorSection>

      <footer className="ai-inline-editor-actions">
        <button type="button" onClick={onCancel}>{t("action.cancel")}</button>
        <button disabled={saving} type="submit">{saving ? t("action.saving") : t("action.save")}</button>
      </footer>
    </form>
  );
}

function TaskEditor({ task, index, draft, setDraft, moveTask }: {
  task: ProposalContent["tasks"][number];
  index: number;
  draft: ProposalContent;
  setDraft: (draft: ProposalContent) => void;
  moveTask: (index: number, offset: -1 | 1) => void;
}) {
  const t = useTranslations("ai");
  const update = (changes: Partial<typeof task>) => setDraft({ ...draft, tasks: draft.tasks.map((item, itemIndex) => itemIndex === index ? { ...item, ...changes } : item) });
  return <article className="ai-inline-task">
    <div className="ai-inline-task-heading"><EditorField label={t("editor.taskTitle")}><input value={task.title} onChange={(event) => update({ title: event.target.value })} /></EditorField><span>{task.estimated_effort_hours}h</span></div>
    <div className="ai-inline-field-grid">
      <EditorField label={t("editor.description")}><textarea rows={2} value={task.description ?? ""} onChange={(event) => update({ description: event.target.value || null })} /></EditorField>
      <EditorField label={t("editor.dueDate")}><input type="date" value={task.due_date ?? ""} onChange={(event) => update({ due_date: event.target.value || null })} /></EditorField>
      <EditorField label={t("editor.milestone")}><select value={task.milestone_ref ?? ""} onChange={(event) => update({ milestone_ref: event.target.value || null })}><option value="">{t("editor.unselected")}</option>{draft.milestones.map((milestone) => <option key={milestone.ref} value={milestone.ref}>{milestone.title}</option>)}</select></EditorField>
      <EditorField label={t("editor.week")}><select value={task.project_week_ref} onChange={(event) => update({ project_week_ref: event.target.value })}>{draft.project_weeks.map((week) => <option key={week.ref} value={week.ref}>{t("editor.weekNumber", { number: week.week_number })}</option>)}</select></EditorField>
      <EditorField label={t("editor.requiredSkills")}><textarea rows={2} value={task.required_skill_labels.join("\n")} onChange={(event) => update({ required_skill_labels: lines(event.target.value) })} /></EditorField>
      <EditorField label={t("editor.effortHours")}><input min={1} type="number" value={task.estimated_effort_hours} onChange={(event) => update({ estimated_effort_hours: Number(event.target.value) })} /></EditorField>
    </div>
    <EditorField label={t("editor.criteriaFor", { task: task.title })}><textarea aria-label={t("editor.criteriaFor", { task: task.title })} rows={3} value={task.acceptance_criteria.join("\n")} onChange={(event) => update({ acceptance_criteria: lines(event.target.value) })} /></EditorField>
    <ItemActions title={task.title} first={index === 0} last={index === draft.tasks.length - 1} onMove={(offset) => moveTask(index, offset)} onRemove={() => setDraft({ ...draft, tasks: draft.tasks.filter((_, taskIndex) => taskIndex !== index), dependencies: draft.dependencies.filter((edge) => edge.predecessor_ref !== task.ref && edge.successor_ref !== task.ref) })} />
  </article>;
}

function EditorSection({ title, className = "", children }: { title: string; className?: string; children: ReactNode }) {
  return <section className={`ai-proposal-section ai-inline-section ${className}`}><h4>{title}</h4>{children}</section>;
}

function EditorField({ label, visuallyHidden = false, children }: { label: string; visuallyHidden?: boolean; children: ReactNode }) {
  return <label className={visuallyHidden ? "ai-inline-field has-hidden-label" : "ai-inline-field"}><span>{label}</span>{children}</label>;
}

function ItemActions({ title, first, last, onMove, onRemove }: { title: string; first: boolean; last: boolean; onMove: (offset: -1 | 1) => void; onRemove: () => void }) {
  const t = useTranslations("ai");
  return <div className="ai-inline-item-actions"><button aria-label={t("action.moveUp", { item: title })} disabled={first} type="button" onClick={() => onMove(-1)}>↑</button><button aria-label={t("action.moveDown", { item: title })} disabled={last} type="button" onClick={() => onMove(1)}>↓</button><button className="is-destructive" type="button" onClick={onRemove}>{t("action.remove")}</button></div>;
}

function Chevron() {
  return <svg aria-hidden="true" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"><path d="m8 10 4 4 4-4" /></svg>;
}

function nextPosition(refs: string[], prefix: string) {
  let position = 1;
  while (refs.includes(`${prefix}${position}`)) position += 1;
  return position;
}

function lines(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
