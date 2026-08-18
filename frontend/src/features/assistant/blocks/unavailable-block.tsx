import { useTranslations } from "next-intl";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "capability_unavailable" }>;

export function UnavailableBlock({ block }: { block: Block }) {
  const t = useTranslations("assistant");
  const known = block.capability === "daily_update" ? t("unavailable.dailyUpdate") : t("unavailable.default");
  return <section className="assistant-block assistant-unavailable" role="status"><h3>{t("unavailable.title")}</h3><p>{known}</p></section>;
}
