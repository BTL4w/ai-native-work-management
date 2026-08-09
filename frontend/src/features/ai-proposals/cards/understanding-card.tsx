import { useTranslations } from "next-intl";

import type { ProposalContent } from "../contracts";

export function UnderstandingCard({ brief, content }: { brief: string; content?: ProposalContent }) {
  const t = useTranslations("ai");
  return (
    <section aria-labelledby="understanding-card" className="ai-card">
      <h3 id="understanding-card">{t("card.understanding")}</h3>
      <p>{brief}</p>
      <p><strong>{t("expectedOutcomes")}</strong></p>
      {content?.goal.expected_outcomes.length ? (
        <ul>{content.goal.expected_outcomes.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : <p>{t("label.unknown")}</p>}
    </section>
  );
}
