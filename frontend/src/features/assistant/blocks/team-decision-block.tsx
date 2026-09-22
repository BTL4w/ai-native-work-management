import { useTranslations } from "next-intl";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "team_decision_result" }>;

export function TeamDecisionBlock({ block }: { block: Block }) {
  const t = useTranslations("assistant.teamDecision");
  return <section className="assistant-block assistant-decision" role="status">
    <h3>{t("title")}</h3>
    <p>{t(block.decision)} · v{block.recommendation_version}</p>
  </section>;
}
