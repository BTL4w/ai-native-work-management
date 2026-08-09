import { useTranslations } from "next-intl";

import type { z } from "zod";
import type { validationResultSchema } from "../contracts";

type Validation = z.infer<typeof validationResultSchema>;

export function ValidationCard({ validation }: { validation: Validation }) {
  const t = useTranslations("ai");
  return (
    <section aria-labelledby="validation-card" className="ai-card" tabIndex={-1}>
      <h3 id="validation-card">{t("card.validation")}</h3>
      <p>{validation.can_approve ? t("validation.ready") : t("validation.blocked")}</p>
      {validation.errors.length ? <ul className="error-message">{validation.errors.map((item, index) => (
        <li key={`${item.path}-${item.code}-${index}`}>{item.path ? `${item.path}: ` : ""}{item.code}</li>
      ))}</ul> : null}
      {validation.warnings.length ? <ul>{validation.warnings.map((item, index) => (
        <li key={`${item.path}-${item.code}-${index}`}>{item.code}</li>
      ))}</ul> : null}
    </section>
  );
}
