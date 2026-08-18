import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslations } from "next-intl";

import { getWorkflowRun } from "@/features/ai-proposals/api";
import { ProposalCard } from "@/features/ai-proposals/cards/proposal-card";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "proposal" }>;

export function PlanningBlock({ block, canManage, onEdit, onRevise, onApprove, onReject }: {
  block: Block;
  canManage: boolean;
  onEdit: (block: Block) => void;
  onRevise: (block: Block, instruction: string) => void;
  onApprove: (block: Block) => void;
  onReject: (block: Block) => void;
}) {
  const t = useTranslations("assistant");
  const [revising, setRevising] = useState(false);
  const [instruction, setInstruction] = useState("");
  const run = useQuery({
    queryKey: ["assistant", "planning-run", block.workflow_run_id, block.current_version ?? block.proposal_version],
    queryFn: () => getWorkflowRun(block.workflow_run_id).then((result) => result.data),
  });
  const proposal = run.data?.current_proposal;
  const stale = block.read_only
    || proposal?.version !== block.proposal_version
    || (block.current_version !== null && block.current_version !== undefined && block.current_version !== block.proposal_version);
  if (run.isPending) return <p role="status">{t("proposal.loading")}</p>;
  if (!proposal) return <SafePlanningFallback block={block} />;
  return <section className={`assistant-planning-card ${stale ? "is-stale" : ""}`}>
    {stale ? <p role="status">{t("proposal.stale", { version: block.current_version ?? proposal.version })}</p> : null}
    <ProposalCard content={proposal.content} version={stale ? proposal.version : block.proposal_version} provenance={proposal.creator_type} editable={false} onEdit={() => undefined} />
    {block.error_codes.length ? <p className="error-message">{t("proposal.validationFailed")}</p> : null}
    {canManage && !stale ? <div className="assistant-proposal-actions">
      <button type="button" onClick={() => onEdit(block)}>{t("proposal.edit")}</button>
      <button type="button" onClick={() => setRevising(true)}>{t("proposal.askAi")}</button>
      <button type="button" onClick={() => onReject(block)}>{t("proposal.reject")}</button>
      <button disabled={block.can_approve === false} type="button" onClick={() => onApprove(block)}>{t("proposal.approve")}</button>
    </div> : null}
    {revising ? <form onSubmit={(event) => { event.preventDefault(); if (instruction.trim()) onRevise(block, instruction.trim()); }}>
      <label>{t("proposal.revisionLabel")}<textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} /></label>
      <button disabled={!instruction.trim()} type="submit">{t("proposal.sendRevision")}</button>
      <button type="button" onClick={() => setRevising(false)}>{t("proposal.cancel")}</button>
    </form> : null}
  </section>;
}

function SafePlanningFallback({ block }: { block: Block }) {
  const t = useTranslations("assistant");
  return <section className="assistant-block assistant-safe-error" role="alert"><p>{t("proposal.unavailable")}</p>{block.manual_fallback ? <p>{block.manual_fallback}</p> : null}</section>;
}
