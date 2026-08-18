import { useState } from "react";
import { useTranslations } from "next-intl";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "activity" }>;

export function ActivityBlock({ block }: { block: Block }) {
  const t = useTranslations("assistant");
  const [expanded, setExpanded] = useState(false);
  return <section className="assistant-block assistant-activity">
    <div className="assistant-activity-summary">
      <span className={`assistant-status-dot status-${block.status.toLowerCase()}`} aria-hidden="true" />
      <p>{t("activity.default")}</p>
      <button aria-expanded={expanded} type="button" onClick={() => setExpanded((value) => !value)}>{t("activity.details")}</button>
    </div>
    {expanded ? <dl>
      {block.agent_id ? <><dt>{t("activity.agent")}</dt><dd>{block.agent_id}</dd></> : null}
      <dt>{t("activity.step")}</dt><dd>{t("activity.safeStep")}</dd>
      <dt>{t("activity.status")}</dt><dd>{t(`status.${block.status}`)}</dd>
    </dl> : null}
  </section>;
}
