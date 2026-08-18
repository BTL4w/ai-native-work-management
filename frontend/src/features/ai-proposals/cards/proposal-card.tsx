import { useTranslations } from "next-intl";

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
  return (
    <section aria-labelledby="proposal-card" className="ai-card">
      <div className="ai-card-heading">
        <div><h3 id="proposal-card">{t("proposalVersion", { version })}</h3><p>{t(`provenance.${provenance}`)}</p></div>
        {editable ? <button type="button" onClick={onEdit}>{t("action.edit")}</button> : null}
      </div>
      <h4>{content.project.title}</h4>
      <p>{content.goal.title}</p>
      <dl className="ai-counts">
        <div><dt>{t("milestones")}</dt><dd>{content.milestones.length}</dd></div>
        <div><dt>{t("tasks")}</dt><dd>{content.tasks.length}</dd></div>
        <div><dt>{t("dependencies")}</dt><dd>{content.dependencies.length}</dd></div>
      </dl>
      {content.project_weeks.toSorted((left, right) => left.week_number - right.week_number).map((week) => (
        <section className="ai-proposal-week" key={week.ref}>
          <h5>{t("editor.weekNumber", { number: week.week_number })} · {week.objective}</h5>
          <p>{week.start_date} → {week.end_date}</p>
          <ul>{content.tasks.filter((task) => task.project_week_ref === week.ref).map((task) => (
            <li key={task.ref}>
              <strong>{task.title}</strong>
              <span>{task.estimated_effort_hours}h · {task.required_skill_labels.join(", ") || "—"}</span>
              <span>{task.assignee_membership_id ? t("taskAssignment.assigned") : t("taskAssignment.unassigned")}</span>
            </li>
          ))}</ul>
        </section>
      ))}
    </section>
  );
}
