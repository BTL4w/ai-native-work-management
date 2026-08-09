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
    </section>
  );
}
