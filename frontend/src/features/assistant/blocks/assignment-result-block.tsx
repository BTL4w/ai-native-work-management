import { useTranslations } from "next-intl";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "assignment_result" }>;

export function AssignmentResultBlock({ block }: { block: Block }) {
  const t = useTranslations("assistant.assignmentResult");
  return <section className="assistant-block assistant-decision" role="status">
    <h3>{t("title")}</h3>
    <p>{t("success", { version: block.task_version })}</p>
    {block.warning_codes.length > 0 ? <ul>
      {block.warning_codes.map((code) => <li key={code}>{t(`warnings.${knownWarning(code)}`)}</li>)}
    </ul> : null}
  </section>;
}

function knownWarning(code: string) {
  return code === "CAPACITY_EXCEEDED" || code === "CAPACITY_UNKNOWN" ? code : "UNKNOWN";
}
