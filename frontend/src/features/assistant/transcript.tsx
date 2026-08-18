import { useTranslations } from "next-intl";

import type { AssistantMessage, AssistantBlock } from "./contracts";
import { ActivityBlock } from "./blocks/activity-block";
import { PlanningBlock } from "./blocks/planning-block";
import { SafeErrorBlock } from "./blocks/safe-error-block";
import { UnavailableBlock } from "./blocks/unavailable-block";
import { WorkEvidenceBlock } from "./blocks/work-evidence-block";

type ProposalBlock = Extract<AssistantBlock, { kind: "proposal" }>;

export function Transcript({ messages, canManage, onEdit, onRevise, onApprove, onReject, onContinueManually }: {
  messages: AssistantMessage[];
  canManage: boolean;
  onEdit: (block: ProposalBlock) => void;
  onRevise: (block: ProposalBlock, instruction: string) => void;
  onApprove: (block: ProposalBlock) => void;
  onReject: (block: ProposalBlock) => void;
  onContinueManually?: () => void;
}) {
  const t = useTranslations("assistant");
  const ordered = messages.toSorted((left, right) => left.sequence - right.sequence);
  return <div className="assistant-transcript" aria-live="polite">
    {ordered.length === 0 ? <div className="assistant-empty"><h2>{t("empty.title")}</h2><p>{t("empty.description")}</p></div> : null}
    {ordered.map((message) => <article className={`assistant-message role-${message.role.toLowerCase()}`} key={message.id}>
      <p className="assistant-message-role">{message.role === "USER" ? t("role.you") : t("role.assistant")}</p>
      <div className="assistant-message-content">{message.content_blocks.map((block, index) => <BlockView
        key={`${message.id}-${index}`}
        block={block}
        canManage={canManage}
        onEdit={onEdit}
        onRevise={onRevise}
        onApprove={onApprove}
        onReject={onReject}
        onContinueManually={onContinueManually}
      />)}</div>
    </article>)}
  </div>;
}

function BlockView({ block, canManage, onEdit, onRevise, onApprove, onReject, onContinueManually }: {
  block: AssistantBlock;
  canManage: boolean;
  onEdit: (block: ProposalBlock) => void;
  onRevise: (block: ProposalBlock, instruction: string) => void;
  onApprove: (block: ProposalBlock) => void;
  onReject: (block: ProposalBlock) => void;
  onContinueManually?: () => void;
}) {
  const t = useTranslations("assistant");
  switch (block.kind) {
    case "text": return <p>{block.text}</p>;
    case "activity": return <ActivityBlock block={block} />;
    case "work_evidence": return <WorkEvidenceBlock block={block} />;
    case "question": return <section className="assistant-block assistant-question"><h3>{t("question.title")}</h3><p>{block.question}</p></section>;
    case "capability_unavailable": return <UnavailableBlock block={block} />;
    case "planning_run": return <section className="assistant-block assistant-activity"><p>{t("planning.status", { status: block.status })}</p></section>;
    case "proposal": return <PlanningBlock block={block} canManage={canManage} onEdit={onEdit} onRevise={onRevise} onApprove={onApprove} onReject={onReject} />;
    case "decision_result": return <section className="assistant-block assistant-decision" role="status"><h3>{t("decision.title")}</h3><p>{t(`decision.${block.decision}`)} · v{block.proposal_version}</p></section>;
    case "safe_error": return <SafeErrorBlock block={block} onContinueManually={onContinueManually} />;
  }
}
