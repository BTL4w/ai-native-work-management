import { useState } from "react";
import { useTranslations } from "next-intl";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "activity" }>;

export function ActivityBlock({ block, groupedBlocks }: { block: Block; groupedBlocks?: Block[] }) {
  const t = useTranslations("assistant");
  const [expanded, setExpanded] = useState(false);
  const blocks = groupedBlocks ?? [block];
  const agents = [...new Set(blocks.flatMap((item) => item.agent_id ? [item.agent_id] : []))];
  const status = aggregateStatus(blocks);
  return <section className="assistant-block assistant-activity">
    <div className="assistant-activity-summary">
      <span className={`assistant-status-dot status-${status.toLowerCase()}`} aria-hidden="true" />
      <p>{t("activity.default")}</p>
      <button aria-expanded={expanded} type="button" onClick={() => setExpanded((value) => !value)}>{t("activity.details")}</button>
    </div>
    {expanded ? <dl>
      {agents.length > 0 ? <><dt>{t("activity.agent")}</dt><dd>{agents.join(", ")}</dd></> : null}
      <dt>{t("activity.step")}</dt><dd>{t("activity.safeSteps", { count: blocks.length })}</dd>
      <dt>{t("activity.status")}</dt><dd>{t(`status.${status}`)}</dd>
    </dl> : null}
  </section>;
}

function aggregateStatus(blocks: Block[]): Block["status"] {
  if (blocks.some((block) => block.status === "FAILED")) return "FAILED";
  if (blocks.some((block) => block.status === "RUNNING")) return "RUNNING";
  if (blocks.some((block) => block.status === "PENDING")) return "PENDING";
  return "COMPLETED";
}
