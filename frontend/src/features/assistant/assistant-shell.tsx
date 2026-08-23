"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { decideApproval, editProposal, getWorkflowRun } from "@/features/ai-proposals/api";
import type { ProposalContent } from "@/features/ai-proposals/contracts";
import { ProposalEditor } from "@/features/ai-proposals/proposal-editor";
import type { MeResponse } from "@/shared/api/contracts";
import { ApiError, isDefinitiveMutationRejection } from "@/shared/api/client";

import { assistantKeys, createConversation, getConversation, listConversations, postAssistantMessage } from "./api";
import { Composer } from "./composer";
import { ConversationList } from "./conversation-list";
import type { AssistantBlock, PostMessageInput } from "./contracts";
import { connectAssistantEvents } from "./event-source";
import { Transcript } from "./transcript";

type ProposalBlock = Extract<AssistantBlock, { kind: "proposal" }>;
type Attempt = { fingerprint: string; key: string };
type Connection = { close(): void };
type ConnectEvents = (options: Parameters<typeof connectAssistantEvents>[0]) => Connection;

function nextKey() { return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`; }
function useAttempt() {
  const current = useRef<Attempt | null>(null);
  return {
    key(payload: unknown) {
      const fingerprint = JSON.stringify(payload);
      if (current.current?.fingerprint !== fingerprint) current.current = { fingerprint, key: nextKey() };
      return current.current.key;
    },
    reset() { current.current = null; },
  };
}

export function AssistantShell({ actor, onContinueManually, onOpenProjects, onOpenMyTasks, onAssignTask, connectEvents = connectAssistantEvents }: {
  actor: MeResponse;
  onContinueManually?: () => void;
  onOpenProjects?: () => void;
  onOpenMyTasks?: () => void;
  onAssignTask?: () => void;
  connectEvents?: ConnectEvents;
}) {
  const t = useTranslations("assistant");
  const locale = useLocale() as "vi" | "en";
  const queryClient = useQueryClient();
  const organizationId = actor.membership.organization_id;
  const membershipId = actor.membership.id;
  const canManage = actor.membership.role !== "EMPLOYEE";
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newConversation, setNewConversation] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState<{ block: ProposalBlock; content: ProposalContent } | null>(null);
  const createAttempt = useAttempt();
  const messageAttempt = useAttempt();
  const editAttempt = useAttempt();
  const decisionAttempt = useAttempt();

  const conversationsKey = assistantKeys.conversations(organizationId, membershipId);
  const conversations = useQuery({ queryKey: conversationsKey, queryFn: listConversations });
  const activeConversationId = newConversation ? null : selectedId ?? conversations.data?.[0]?.id ?? null;
  const snapshotKey = activeConversationId ? assistantKeys.conversation(organizationId, membershipId, activeConversationId) : null;
  const snapshot = useQuery({
    queryKey: snapshotKey ?? [...assistantKeys.scope(organizationId, membershipId), "new"],
    queryFn: () => getConversation(activeConversationId as string).then((result) => result.data),
    enabled: activeConversationId !== null,
  });
  const projectedSequence = snapshot.data?.conversation.last_event_sequence ?? 0;
  useEffect(() => {
    if (!activeConversationId) return;
    const connection = connectEvents({
      conversationId: activeConversationId,
      initialSequence: projectedSequence,
      onSequence: () => void queryClient.invalidateQueries({ queryKey: assistantKeys.conversation(organizationId, membershipId, activeConversationId) }),
      onPoll: () => void queryClient.invalidateQueries({ queryKey: assistantKeys.conversation(organizationId, membershipId, activeConversationId) }),
    });
    return () => connection.close();
  }, [activeConversationId, connectEvents, membershipId, organizationId, projectedSequence, queryClient]);

  const orderedMessages = snapshot.data?.messages.toSorted((left, right) => right.sequence - left.sequence) ?? [];
  const latestUserSequence = orderedMessages.find((item) => item.role === "USER")?.sequence ?? 0;
  const questionMessage = orderedMessages.find((item) =>
    item.role === "ASSISTANT"
    && item.sequence > latestUserSequence
    && item.content_blocks.some((block) => block.kind === "question"),
  );
  const latestQuestion = questionMessage?.content_blocks.find(
    (block): block is Extract<AssistantBlock, { kind: "question" }> => block.kind === "question",
  );

  async function send(input: PostMessageInput, version?: number) {
    if (submitting) return;
    setSubmitting(true); setError(null);
    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const created = await createConversation({ locale, title: null }, createAttempt.key({ locale, title: null }));
        createAttempt.reset();
        conversationId = created.data.id;
        setSelectedId(conversationId); setNewConversation(false);
        await queryClient.invalidateQueries({ queryKey: conversationsKey });
      }
      await postAssistantMessage(conversationId, input, messageAttempt.key({ conversationId, input, version }), version);
      messageAttempt.reset(); setMessage("");
      await queryClient.invalidateQueries({ queryKey: assistantKeys.conversation(organizationId, membershipId, conversationId) });
    } catch (caught) {
      setError(caught);
      if (isDefinitiveMutationRejection(caught)) messageAttempt.reset();
    } finally { setSubmitting(false); }
  }

  function submitComposer() {
    const normalized = message.trim();
    if (!normalized) return;
    const workflowRunId = latestQuestion?.response_context.workflow_run_id;
    const cardAction = typeof workflowRunId === "string" ? {
      kind: "PLANNING_INPUT" as const,
      workflow_run_id: workflowRunId,
    } : undefined;
    void send({ message: normalized, locale, ...(cardAction ? { card_action: cardAction } : {}) });
  }

  async function openEditor(block: ProposalBlock) {
    setError(null);
    try {
      const run = await getWorkflowRun(block.workflow_run_id);
      if (run.data.current_proposal) setEditing({ block, content: run.data.current_proposal.content });
    } catch (caught) { setError(caught); }
  }
  async function saveEdit(content: ProposalContent) {
    if (!editing || submitting) return;
    const payload = { proposalId: editing.block.proposal_id, version: editing.block.proposal_version, content };
    setSubmitting(true); setError(null);
    try {
      await editProposal(editing.block.proposal_id, content, editing.block.proposal_version, editAttempt.key(payload));
      editAttempt.reset(); setEditing(null); await snapshot.refetch();
    } catch (caught) {
      setError(caught); if (isDefinitiveMutationRejection(caught)) editAttempt.reset();
      if (caught instanceof ApiError && ["RESOURCE_VERSION_MISMATCH", "PROPOSAL_STALE"].includes(caught.code)) await snapshot.refetch();
    } finally { setSubmitting(false); }
  }
  function revise(block: ProposalBlock, instruction: string) {
    void send({ message: instruction, locale, card_action: { kind: "PLANNING_REVISE", workflow_run_id: block.workflow_run_id, proposal_id: block.proposal_id } }, block.proposal_version);
  }
  async function decide(block: ProposalBlock, decision: "APPROVE" | "REJECT") {
    if (!block.approval_id || submitting) return;
    const payload = { approvalId: block.approval_id, decision, version: block.proposal_version };
    setSubmitting(true); setError(null);
    try {
      await decideApproval(block.approval_id, decision, block.proposal_version, null, decisionAttempt.key(payload));
      decisionAttempt.reset(); await snapshot.refetch();
    } catch (caught) {
      setError(caught); if (isDefinitiveMutationRejection(caught)) decisionAttempt.reset();
      if (caught instanceof ApiError && ["RESOURCE_VERSION_MISMATCH", "PROPOSAL_STALE", "APPROVAL_STATE_CONFLICT"].includes(caught.code)) await snapshot.refetch();
    } finally { setSubmitting(false); }
  }

  const visibleError = error ?? snapshot.error ?? conversations.error;

  return <section className={`assistant-shell ${collapsed ? "is-sidebar-collapsed" : ""}`} aria-labelledby="assistant-title">
    <ConversationList
      actor={actor}
      conversations={conversations.data ?? []}
      selectedId={activeConversationId}
      collapsed={collapsed}
      onSelect={(id) => { setSelectedId(id); setNewConversation(false); setError(null); }}
      onNew={() => { setSelectedId(null); setNewConversation(true); setMessage(""); setError(null); }}
      onToggle={() => setCollapsed((value) => !value)}
      onOpenProjects={onOpenProjects}
      onOpenMyTasks={onOpenMyTasks}
      onAssignTask={onAssignTask}
    />
    <div className="assistant-main-pane">
      <header className="assistant-header"><div><p>{t("eyebrow")}</p><h1 id="assistant-title">{t("title")}</h1></div></header>
      {visibleError ? <div className="assistant-safe-notice" role="alert"><p>{t("error.safe")}</p>{visibleError instanceof ApiError && visibleError.requestId ? <p>{t("error.reference", { requestId: visibleError.requestId })}</p> : null}</div> : null}
      {snapshot.isPending && activeConversationId ? <p role="status">{t("loading")}</p> : <Transcript
        messages={snapshot.data?.messages ?? []}
        canManage={canManage}
        onEdit={(block) => void openEditor(block)}
        onRevise={revise}
        onApprove={(block) => void decide(block, "APPROVE")}
        onReject={(block) => void decide(block, "REJECT")}
        onContinueManually={onContinueManually}
      />}
      <Composer value={message} disabled={submitting} autoFocus={!activeConversationId || (snapshot.data?.messages.length ?? 0) === 0} onChange={setMessage} onSubmit={submitComposer} />
    </div>
    {editing ? <div className="assistant-editor-dialog" role="dialog" aria-modal="true" aria-label={t("proposal.edit")}><ProposalEditor initial={editing.content} saving={submitting} onCancel={() => setEditing(null)} onSave={(content) => void saveEdit(content)} /></div> : null}
  </section>;
}
