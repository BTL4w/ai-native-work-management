import { useTranslations } from "next-intl";

import type { ProposalContent } from "../contracts";

export function AssumptionsCard({ content }: { content: ProposalContent }) {
  const t = useTranslations("ai");
  return (
    <section aria-labelledby="assumptions-card" className="ai-card">
      <h3 id="assumptions-card">{t("card.assumptions")}</h3>
      {content.assumptions.length ? (
        <ul>{content.assumptions.map((item, index) => (
          <li key={index}>{item.description}</li>
        ))}</ul>
      ) : <p>{t("noAssumptions")}</p>}
    </section>
  );
}
