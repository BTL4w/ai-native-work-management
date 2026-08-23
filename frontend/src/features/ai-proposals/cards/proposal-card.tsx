import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import type { ProposalContent } from "../contracts";

export function ProposalCard({
  content,
  version,
  provenance,
  onEdit,
  editable,
}: {
  content: ProposalContent;
  version: number;
  provenance: string;
  onEdit: () => void;
  editable: boolean;
}) {
  const t = useTranslations("ai");
  const tasksByRef = new Map(content.tasks.map((task) => [task.ref, task.title]));
  return (
    <section className="ai-card ai-proposal-card">
      <div className="ai-card-heading">
        <div className="ai-proposal-kicker"><span>{t("proposalVersion", { version })}</span><span>·</span><span>{t(`provenance.${provenance}`)}</span></div>
        {editable ? <button type="button" onClick={onEdit}>{t("action.edit")}</button> : null}
      </div>
      <header className="ai-proposal-title">
        <h3>{content.project.title}</h3>
        {content.project.description ? <p>{content.project.description}</p> : null}
        <dl>
          <div><dt>{t("editor.startDate")}</dt><dd>{content.project.start_date ?? t("label.unknown")}</dd></div>
          <div><dt>{t("editor.projectDueDate")}</dt><dd>{content.project.due_date ?? t("label.unknown")}</dd></div>
        </dl>
      </header>

      <section className="ai-proposal-section ai-proposal-goal">
        <p className="ai-proposal-section-label">{t("goal")}</p>
        <p className="ai-proposal-goal-title">{content.goal.title}</p>
        {content.goal.description ? <p>{content.goal.description}</p> : null}
        {content.goal.expected_outcomes.length ? <ul>{content.goal.expected_outcomes.map((outcome) => <li key={outcome}>{outcome}</li>)}</ul> : null}
      </section>

      {content.assumptions.length ? <section className="ai-proposal-section">
        <h4>{t("editor.assumptions")}</h4>
        <ul className="ai-proposal-assumptions">{content.assumptions.map((assumption) => <li key={`${assumption.description}-${assumption.source}`}><span>{assumption.description}</span><small>{assumption.source}</small></li>)}</ul>
      </section> : null}

      {content.milestones.length ? <section className="ai-proposal-section">
        <h4>{t("milestones")}</h4>
        <ul className="ai-proposal-milestones">{content.milestones.map((milestone) => <li key={milestone.ref}><span>{milestone.title}</span><time>{milestone.due_date ?? t("label.unknown")}</time></li>)}</ul>
      </section> : null}

      <section className="ai-proposal-section ai-proposal-timeline">
        <h4>{t("projectWeeks")}</h4>
        {content.project_weeks.toSorted((left, right) => left.week_number - right.week_number).map((week) => (
          <ProposalWeek
            key={`${version}-${week.ref}`}
            week={week}
            tasks={content.tasks.filter((task) => task.project_week_ref === week.ref)}
          />
        ))}
      </section>

      {content.dependencies.length ? <section className="ai-proposal-section ai-proposal-dependencies">
        <h4>{t("dependencies")}</h4>
        <ul>{content.dependencies.map((dependency) => <li key={`${dependency.predecessor_ref}-${dependency.successor_ref}`}>{tasksByRef.get(dependency.predecessor_ref) ?? dependency.predecessor_ref} → {tasksByRef.get(dependency.successor_ref) ?? dependency.successor_ref}</li>)}</ul>
      </section> : null}
    </section>
  );
}

function ProposalWeek({ week, tasks }: {
  week: ProposalContent["project_weeks"][number];
  tasks: ProposalContent["tasks"];
}) {
  const t = useTranslations("ai");
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();

  return <section className={`ai-proposal-week ${expanded ? "is-expanded" : ""}`}>
    <button
      aria-controls={contentId}
      aria-expanded={expanded}
      className="ai-proposal-week-heading"
      type="button"
      onClick={() => setExpanded((value) => !value)}
    >
      <span className="ai-proposal-week-summary">
        <span className="ai-proposal-week-number">{t("editor.weekNumber", { number: week.week_number })}</span>
        <span className="ai-proposal-week-objective">{week.objective}</span>
      </span>
      <span className="ai-proposal-week-meta">
        <time>{week.start_date} → {week.end_date}</time>
        <svg aria-hidden="true" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2"><path d="m8 10 4 4 4-4" /></svg>
      </span>
    </button>
    {expanded ? <ul className="ai-proposal-week-content" id={contentId}>{tasks.map((task) => (
      <li className="ai-proposal-task" key={task.ref}>
        <div className="ai-proposal-task-heading"><strong>{task.title}</strong><span>{task.estimated_effort_hours}h</span></div>
        <p>{task.required_skill_labels.join(" · ") || t("noRequiredSkills")}</p>
        <span className="ai-proposal-assignment">{task.assignee_membership_id ? t("taskAssignment.assigned") : t("taskAssignment.unassigned")}</span>
        {task.acceptance_criteria.length ? <div className="ai-proposal-criteria"><p>{t("acceptanceCriteria")}</p><ul>{task.acceptance_criteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul></div> : null}
      </li>
    ))}</ul> : null}
  </section>;
}
