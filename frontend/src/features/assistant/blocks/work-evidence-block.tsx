import { useTranslations } from "next-intl";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "work_evidence" }>;

export function WorkEvidenceBlock({ block }: { block: Block }) {
  const t = useTranslations("assistant");
  return <section className="assistant-block assistant-evidence">
    <h3>{t("evidence.title")}</h3>
    <p>{block.summary}</p>
    <ul>{block.evidence.map((item) => <li key={item.evidence_id}>
      <span>{item.resource_type}{item.version ? ` · v${item.version}` : ""}</span>
      <code>{item.resource_id}</code>
    </li>)}</ul>
  </section>;
}
