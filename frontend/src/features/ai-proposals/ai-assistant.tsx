"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";

import type { MeResponse } from "@/shared/api/contracts";
import { ApiError, isDefinitiveMutationRejection } from "@/shared/api/client";

import { decideApproval, editProposal, getWorkflowRun, listPlanningRuns, postManagerMessage, startPlanningRun } from "./api";
import { ApprovalCard } from "./cards/approval-card";
import { AssumptionsCard } from "./cards/assumptions-card";
import { ProposalCard } from "./cards/proposal-card";
import { UnderstandingCard } from "./cards/understanding-card";
import { ValidationCard } from "./cards/validation-card";
import type { ApprovalResult, ProposalContent } from "./contracts";
import { connectWorkflowEvents, type WorkflowConnectionStatus } from "./event-source";
import { ProposalEditor } from "./proposal-editor";
import { RunList } from "./run-list";

type Connection = { close(): void };
type ConnectEvents = (options: Parameters<typeof connectWorkflowEvents>[0]) => Connection;
type Attempt = { fingerprint: string; key: string };
type PendingDecision = {
  approvalId: string;
  decision: "APPROVE" | "REJECT";
  version: number;
};

function newKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function useAttempt() {
  const ref = useRef<Attempt | null>(null);
  return {
    key(payload: unknown) {
      const fingerprint = JSON.stringify(payload);
      if (ref.current?.fingerprint !== fingerprint) ref.current = { fingerprint, key: newKey() };
      return ref.current.key;
    },
    reset() { ref.current = null; },
  };
}

export function AiAssistant({
  actor,
  onContinueManually,
  connectEvents = connectWorkflowEvents,
}: {
  actor: MeResponse;
  onContinueManually?: () => void;
  connectEvents?: ConnectEvents;
}) {
  const t = useTranslations("ai");
  const locale = useLocale() as "vi" | "en";
  const queryClient = useQueryClient();
  const organizationId = actor.membership.organization_id;
  const membershipId = actor.membership.id;
  const scope = ["ai-planning", organizationId, membershipId] as const;
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [managerAnswer, setManagerAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [decision, setDecision] = useState<PendingDecision | null>(null);
  const [decisionResult, setDecisionResult] = useState<ApprovalResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [connection, setConnection] = useState<WorkflowConnectionStatus>("connecting");
  const startAttempt = useAttempt();
  const messageAttempt = useAttempt();
  const editAttempt = useAttempt();
  const decisionAttempt = useAttempt();

  const runs = useQuery({ queryKey: [...scope, "runs"], queryFn: listPlanningRuns });
  const snapshot = useQuery({
    queryKey: [...scope, "run", selectedRunId],
    queryFn: () => getWorkflowRun(selectedRunId as string).then((result) => result.data),
    enabled: selectedRunId !== null,
  });
  useEffect(() => {
    if (!selectedRunId) return;
    const current = connectEvents({
      runId: selectedRunId,
      onSequence: () => void queryClient.invalidateQueries({ queryKey: ["ai-planning", organizationId, membershipId, "run", selectedRunId] }),
      onStatus: setConnection,
      onPoll: () => void queryClient.invalidateQueries({ queryKey: ["ai-planning", organizationId, membershipId, "run", selectedRunId] }),
    });
    return () => current.close();
  }, [connectEvents, membershipId, organizationId, queryClient, selectedRunId]);

  async function beginPlanning(normalized: string) {
    if (!normalized || submitting) return;
    setSubmitting(true); setError(null);
    try {
      const result = await startPlanningRun(normalized, locale, startAttempt.key({ normalized, locale }));
      startAttempt.reset(); setMessage(""); setSelectedRunId(result.data.run_id);
      await queryClient.invalidateQueries({ queryKey: [...scope, "runs"] });
    } catch (caught) {
      setError(caught);
      if (isDefinitiveMutationRejection(caught)) startAttempt.reset();
    } finally { setSubmitting(false); }
  }

  function start(event: FormEvent) {
    event.preventDefault();
    void beginPlanning(message.trim());
  }

  async function answer(event: FormEvent) {
    event.preventDefault();
    if (!selectedRunId || !managerAnswer.trim() || submitting) return;
    setSubmitting(true); setError(null);
    try {
      const payload = managerAnswer.trim();
      await postManagerMessage(selectedRunId, payload, messageAttempt.key(payload));
      messageAttempt.reset(); setManagerAnswer(""); await snapshot.refetch();
    } catch (caught) {
      setError(caught); if (isDefinitiveMutationRejection(caught)) messageAttempt.reset();
    } finally { setSubmitting(false); }
  }

  async function saveProposal(content: ProposalContent) {
    const proposal = snapshot.data?.current_proposal;
    if (!proposal || submitting) return;
    setSubmitting(true); setError(null);
    try {
      await editProposal(proposal.proposal_id, content, proposal.version, editAttempt.key({ content, version: proposal.version }));
      editAttempt.reset(); setEditing(false); await snapshot.refetch();
    } catch (caught) {
      setError(caught); if (isDefinitiveMutationRejection(caught)) editAttempt.reset();
      if (caught instanceof ApiError && ["RESOURCE_VERSION_MISMATCH", "PROPOSAL_STALE"].includes(caught.code)) await snapshot.refetch();
    } finally { setSubmitting(false); }
  }

  async function confirmDecision(reason: string | null) {
    if (!decision || submitting) return;
    const payload = { decision: decision.decision, reason, version: decision.version };
    setSubmitting(true); setError(null);
    try {
      const result = await decideApproval(decision.approvalId, decision.decision, decision.version, reason, decisionAttempt.key(payload));
      decisionAttempt.reset(); setDecision(null); setDecisionResult(result.data); await snapshot.refetch();
    } catch (caught) {
      setError(caught); if (isDefinitiveMutationRejection(caught)) decisionAttempt.reset();
      if (caught instanceof ApiError && ["RESOURCE_VERSION_MISMATCH", "PROPOSAL_STALE", "APPROVAL_STATE_CONFLICT"].includes(caught.code)) await snapshot.refetch();
    } finally { setSubmitting(false); }
  }

  const run = snapshot.data;
  const proposal = run?.current_proposal;
  const visibleError = error ?? snapshot.error ?? runs.error;
  const canDecide = Boolean(
    proposal?.status === "READY_FOR_DECISION"
      && proposal.approval_id
      && run?.allowed_actions.includes("DECIDE_APPROVAL"),
  );
  const canApprove = canDecide && Boolean(proposal?.validation_result.can_approve);

  function openDecision(nextDecision: "APPROVE" | "REJECT") {
    if (!proposal?.approval_id || !canDecide) return;
    setDecision({
      approvalId: proposal.approval_id,
      decision: nextDecision,
      version: proposal.version,
    });
  }

  return (
    <div className="ai-assistant-layout">
      <aside><RunList runs={runs.data ?? []} selectedId={selectedRunId} onSelect={(id) => { setSelectedRunId(id); setDecisionResult(null); }} /></aside>
      <section className="ai-assistant-main" aria-labelledby="ai-assistant-title">
        <header><p className="eyebrow">{t("eyebrow")}</p><h1 id="ai-assistant-title">{t("title")}</h1><p>{t("description")}</p></header>
        <form className="ai-chat-form" onSubmit={start}>
          <label htmlFor="ai-planning-message">{t("chat.requestLabel")}</label>
          <textarea id="ai-planning-message" maxLength={8000} value={message} onChange={(event) => setMessage(event.target.value)} />
          <button disabled={submitting || !message.trim()} type="submit">{t("chat.submit")}</button>
        </form>
        {visibleError ? <ErrorNotice error={visibleError} onRetry={() => selectedRunId ? void snapshot.refetch() : void runs.refetch()} /> : null}
        {snapshot.isPending && selectedRunId ? <p aria-live="polite">{t("loading")}</p> : null}
        {run ? (
          <div className="ai-wizard">
            <ol aria-label={t("stepperLabel")} className="ai-stepper">
              {["understanding", "assumptions", "proposal", "review"].map((step, index) => <li key={step}><span>{index + 1}</span>{t(`step.${step}`)}</li>)}
            </ol>
            <p aria-live="polite">{t(`status.${run.status}`)}</p>
            {proposal?.status === "VALIDATING" ? <p aria-live="polite" role="status">{t("validating")}</p> : null}
            {connection === "reconnecting" ? <p role="status">{t("reconnecting")}</p> : null}
            <UnderstandingCard brief={run.input_goal_text} content={proposal?.content} />
            {run.status === "NEEDS_INPUT" ? <form className="ai-card" onSubmit={answer}><h3>{t("needsInput")}</h3><label>{t("chat.answerLabel")}<textarea value={managerAnswer} onChange={(event) => setManagerAnswer(event.target.value)} /></label><button disabled={submitting || !managerAnswer.trim()} type="submit">{t("chat.continue")}</button></form> : null}
            {proposal ? <AssumptionsCard content={proposal.content} /> : null}
            {proposal && editing ? <ProposalEditor initial={proposal.content} saving={submitting} onCancel={() => setEditing(false)} onSave={(content) => void saveProposal(content)} /> : null}
            {proposal && !editing ? <ProposalCard content={proposal.content} version={proposal.version} provenance={proposal.creator_type} editable={run.allowed_actions.includes("EDIT_PROPOSAL")} onEdit={() => setEditing(true)} /> : null}
            {proposal?.previous_version ? <ProposalDiff current={proposal.content} previous={proposal.previous_version.content} summary={proposal.change_summary} /> : null}
            {proposal ? <ValidationCard validation={proposal.validation_result} /> : null}
            {proposal?.status === "STALE" ? <section className="ai-card error-message"><h3>{t("stale.title")}</h3><p>{t("stale.description")}</p><button type="button" onClick={() => void snapshot.refetch()}>{t("action.reload")}</button></section> : null}
            {proposal ? <ApprovalCard version={proposal.version} canDecide={canDecide} canApprove={canApprove} onApprove={() => openDecision("APPROVE")} onReject={() => openDecision("REJECT")} /> : null}
            {run.status === "FAILED" ? <section className="ai-card"><h3>{t("failed.title")}</h3><p>{t("failed.description")}</p><div className="ai-actions"><button disabled={submitting} type="button" onClick={() => void beginPlanning(run.input_goal_text.trim())}>{t("action.retry")}</button><button type="button" onClick={onContinueManually}>{t("action.continueManually")}</button></div></section> : null}
            {decisionResult?.created.project_id ? <p role="status">{t("createdProject")}</p> : null}
          </div>
        ) : null}
        {decision ? <DecisionDialog decision={decision.decision} version={decision.version} submitting={submitting} onCancel={() => setDecision(null)} onConfirm={(reason) => void confirmDecision(reason)} /> : null}
      </section>
    </div>
  );
}

function ProposalDiff({ current, previous, summary }: { current: ProposalContent; previous: ProposalContent; summary: string | null }) {
  const t = useTranslations("ai");
  const changes = [
    current.project.title === previous.project.title ? null : `${t("editor.projectTitle")}: ${previous.project.title} → ${current.project.title}`,
    current.goal.title === previous.goal.title ? null : `${t("editor.goalTitle")}: ${previous.goal.title} → ${current.goal.title}`,
    current.milestones.length === previous.milestones.length ? null : `${t("milestones")}: ${previous.milestones.length} → ${current.milestones.length}`,
    current.tasks.length === previous.tasks.length ? null : `${t("tasks")}: ${previous.tasks.length} → ${current.tasks.length}`,
    current.dependencies.length === previous.dependencies.length ? null : `${t("dependencies")}: ${previous.dependencies.length} → ${current.dependencies.length}`,
  ].filter((item): item is string => item !== null);
  return <section className="ai-card"><h3>{t("changes")}</h3>{summary ? <p>{summary}</p> : null}{changes.length ? <ul>{changes.map((item) => <li key={item}>{item}</li>)}</ul> : <p>{t("noVisibleChanges")}</p>}</section>;
}

function ErrorNotice({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const t = useTranslations("ai");
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return <div className="error-message" role="alert"><p>{t("error.safe")}</p>{requestId ? <p>{t("error.reference", { requestId })}</p> : null}<button type="button" onClick={onRetry}>{t("action.retry")}</button></div>;
}

function DecisionDialog({ decision, version, submitting, onCancel, onConfirm }: { decision: "APPROVE" | "REJECT"; version: number; submitting: boolean; onCancel: () => void; onConfirm: (reason: string | null) => void }) {
  const t = useTranslations("ai");
  const [reason, setReason] = useState("");
  const panelRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    confirmRef.current?.focus();
    return () => opener?.focus();
  }, []);

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !submitting) {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(panelRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), textarea:not(:disabled)") ?? []);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return <div aria-modal="true" className="dialog-backdrop" role="dialog" aria-labelledby="ai-decision-title" onKeyDown={handleKeyDown}><div ref={panelRef} className="dialog-panel"><h2 id="ai-decision-title">{t(`dialog.${decision}`)}</h2><p>{t("proposalVersion", { version })}</p><label>{t("dialog.reason")}<textarea maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} /></label><div className="ai-actions"><button type="button" onClick={onCancel}>{t("action.cancel")}</button><button ref={confirmRef} disabled={submitting} type="button" onClick={() => onConfirm(reason.trim() || null)}>{t(`dialog.confirm.${decision}`)}</button></div></div></div>;
}
