"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";

import { listSkills } from "@/features/people-capacity/api";
import { listProjectWeeks } from "@/features/planning/api";
import type { Task } from "@/features/work/contracts";
import { ApiError, isDefinitiveMutationRejection } from "@/shared/api/client";

import { confirmRequirements, createRecommendation, decideRecommendation, deriveRequirements, getProjectTeam, getRankingPreview, getRecommendation, getRequirements, listAllProjectTasks, recordRecommendationFeedback, refreshRequirements, reviseRecommendation, reviseRequirements } from "./api";
import type { CandidateOverrideInput, RecommendationVersion, RequirementItemInput, TeamRequirementSet } from "./contracts";
import { RankingPreviewView } from "./ranking-preview";
import { RecommendationCard } from "./recommendation-card";
import { RecommendationEditor } from "./recommendation-editor";
import { RecommendationHistory } from "./recommendation-history";
import { CurrentTeam } from "./current-team";
import { RequirementsEditor } from "./requirements-editor";

const key = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;

export function TeamPanel({ projectId, canManage, onOpenTask }: { projectId: string; canManage: boolean; onOpenTask?: (task: Task) => void }) {
  const t = useTranslations("projectTeam");
  const client = useQueryClient();
  const queryKey = ["projectTeam", projectId, "requirements"] as const;
  const requirements = useQuery({ queryKey, queryFn: async () => (await getRequirements(projectId)).data, retry: false });
  const skills = useQuery({ queryKey: ["projectTeam", projectId, "skills"], queryFn: listSkills });
  const weeks = useQuery({ queryKey: ["projectTeam", projectId, "weeks"], queryFn: () => listProjectWeeks(projectId) });
  const tasks = useQuery({ queryKey: ["projectTeam", projectId, "tasks"], queryFn: () => listAllProjectTasks(projectId) });
  const team = useQuery({ queryKey: ["projectTeam", projectId, "current"], queryFn: () => getProjectTeam(projectId), retry: false });
  const preview = useQuery({ queryKey: ["projectTeam", projectId, "ranking", requirements.data?.version], queryFn: () => getRankingPreview(projectId), enabled: Boolean(requirements.data), retry: false });
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState<RecommendationVersion | null>(null);
  const [recommendationHistory, setRecommendationHistory] = useState<RecommendationVersion[]>([]);
  const [editingRecommendation, setEditingRecommendation] = useState(false);
  const [staleRecommendation, setStaleRecommendation] = useState<RecommendationVersion | null>(null);
  const [pendingOverrides, setPendingOverrides] = useState<CandidateOverrideInput[] | undefined>();
  const [decisionAction, setDecisionAction] = useState<"approve" | "reject" | null>(null);
  const [decisionNote, setDecisionNote] = useState("");
  const [decisionValidation, setDecisionValidation] = useState<string | null>(null);
  const [feedbackWarning, setFeedbackWarning] = useState<string | null>(null);
  const mutationAttempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const missing = requirements.error instanceof ApiError && requirements.error.code === "RESOURCE_NOT_FOUND";

  function idempotencyKey(payload: unknown) {
    const fingerprint = JSON.stringify(payload);
    if (mutationAttempt.current?.fingerprint !== fingerprint) {
      mutationAttempt.current = { fingerprint, key: key() };
    }
    return mutationAttempt.current.key;
  }

  async function mutate(operation: () => Promise<{ data: TeamRequirementSet }>) {
    setSubmitting(true); setError(null); setFeedbackWarning(null);
    try { const result = await operation(); mutationAttempt.current = null; client.setQueryData(queryKey, result.data); setEditing(false); await client.invalidateQueries({ queryKey: ["projectTeam", projectId, "ranking"] }); }
    catch (caught) { if (isDefinitiveMutationRejection(caught)) mutationAttempt.current = null; setError(caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH" ? t("errors.stale") : t("errors.mutation")); }
    finally { setSubmitting(false); }
  }

  async function startRecommendation(value: TeamRequirementSet) {
    const payload = { action: "create-recommendation", requirementSetId: value.id, requirementVersion: value.version };
    setSubmitting(true); setError(null);
    try {
      const result = await createRecommendation(projectId, value.id, value.version, idempotencyKey(payload));
      mutationAttempt.current = null;
      setRecommendation(result.data);
    } catch (caught) {
      if (isDefinitiveMutationRejection(caught)) mutationAttempt.current = null;
      setError(t("recommendation.errors.create"));
    } finally {
      setSubmitting(false);
    }
  }

  async function saveRecommendation(overrides: CandidateOverrideInput[]) {
    if (!recommendation) return;
    const base = recommendation;
    const payload = { action: "revise-recommendation", recommendationId: base.recommendation_id, version: base.version, overrides };
    setSubmitting(true); setError(null); setFeedbackWarning(null);
    try {
      const result = await reviseRecommendation(base.recommendation_id, overrides, base.version, idempotencyKey(payload));
      mutationAttempt.current = null;
      setRecommendationHistory((current) => [...current, base]);
      setRecommendation(result.data);
      setPendingOverrides(undefined);
      setStaleRecommendation(null);
      setEditingRecommendation(false);
      const comment = overrides.map((override) => override.override_reason?.trim()).filter(Boolean).join("; ");
      try {
        await recordRecommendationFeedback(base.recommendation_id, result.data.version, "override", comment, idempotencyKey({ action: "feedback", recommendationId: base.recommendation_id, version: result.data.version, kind: "override", comment }));
        mutationAttempt.current = null;
      } catch (caught) {
        if (isDefinitiveMutationRejection(caught)) mutationAttempt.current = null;
        setFeedbackWarning(t("recommendationFeedbackWarning"));
      }
    } catch (caught) {
      if (isDefinitiveMutationRejection(caught)) mutationAttempt.current = null;
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        try {
          const latest = await getRecommendation(base.recommendation_id);
          setPendingOverrides(overrides);
          setStaleRecommendation(latest.data);
        } catch {
          setError(t("recommendation.errors.revise"));
        }
      } else {
        setError(t("recommendation.errors.revise"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function decide() {
    if (!recommendation || !decisionAction) return;
    const base = recommendation;
    const reason = decisionNote.trim() || null;
    if (decisionAction === "reject" && !reason) {
      setDecisionValidation(t("teamDecisionRejectReasonRequired"));
      return;
    }
    const payload = { action: decisionAction, recommendationId: base.recommendation_id, version: base.version, reason };
    setSubmitting(true); setError(null); setFeedbackWarning(null);
    try {
      const result = await decideRecommendation(base.recommendation_id, base.version, decisionAction, reason, idempotencyKey(payload));
      mutationAttempt.current = null;
      setRecommendation(result.data);
      setDecisionAction(null);
      setDecisionNote("");
      setDecisionValidation(null);
      await client.invalidateQueries({ queryKey: ["projectTeam", projectId, "current"] });
      try {
        await recordRecommendationFeedback(base.recommendation_id, base.version, decisionAction === "approve" ? "accept" : "reject", decisionNote.trim(), idempotencyKey({ ...payload, action: "feedback" }));
        mutationAttempt.current = null;
      } catch (caught) {
        if (isDefinitiveMutationRejection(caught)) mutationAttempt.current = null;
        setFeedbackWarning(t("teamDecisionFeedbackWarning"));
      }
    } catch (caught) {
      if (isDefinitiveMutationRejection(caught)) mutationAttempt.current = null;
      setError(t("teamDecisionError"));
    } finally {
      setSubmitting(false);
    }
  }
  const skillNames = Object.fromEntries((skills.data ?? []).map((skill) => [skill.id, skill.name]));
  const weekLabels = Object.fromEntries((weeks.data ?? []).map((week) => [week.id, t("requirements.week", { number: week.week_number })]));
  const taskNames = Object.fromEntries((tasks.data ?? []).map((task) => [task.id, task.title]));
  const requirementLabels = Object.fromEntries((requirements.data?.items ?? []).map((item) => [item.id, `${skillNames[item.skill_id] ?? item.skill_id} · ${weekLabels[item.project_week_id] ?? item.project_week_id}`]));

  if (requirements.isPending) return <p role="status">{t("loading")}</p>;
  if (missing) return <section><h3 className="text-xl font-semibold">{t("requirements.title")}</h3><p className="mt-3 text-sm text-slate-600">{t("requirements.notDerived")}</p>{canManage ? <button className="primary-button mt-5" disabled={submitting} type="button" onClick={() => void mutate(() => deriveRequirements(projectId, idempotencyKey({ action: "derive", projectId }))) }>{t("actions.derive")}</button> : null}{error ? <p role="alert" className="error-message mt-4">{error}</p> : null}</section>;
  if (requirements.error || !requirements.data) return <p role="alert" className="error-message">{t("errors.load")}</p>;
  const value = requirements.data;
  return <section>
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="eyebrow">{t("eyebrow")}</p><h3 className="text-xl font-semibold">{t("requirements.title")}</h3><p className="mt-2 text-sm text-slate-600">{t(`status.${value.status}`, { version: value.version })}</p></div>{canManage && !editing ? <button className="secondary-button" type="button" onClick={() => setEditing(true)}>{t("actions.edit")}</button> : null}</div>
    {editing ? <RequirementsEditor items={value.items} skills={(skills.data ?? []).map((skill) => ({ id: skill.id, name: skill.name }))} weeks={(weeks.data ?? []).map((week) => ({ id: week.id, label: weekLabels[week.id] }))} tasks={(tasks.data ?? []).map((task) => ({ id: task.id, title: task.title }))} submitting={submitting} onCancel={() => setEditing(false)} onSave={(items: RequirementItemInput[]) => {
      const coveredTasks = new Set(items.flatMap((item) => item.source_task_ids));
      const unresolved = value.incomplete_items.filter((item) => !coveredTasks.has(item.task_id));
      const payload = { action: "revise" as const, items, incomplete_items: unresolved };
      void mutate(() => reviseRequirements(projectId, payload, value.version, idempotencyKey({ ...payload, version: value.version })));
    }} /> : <details className="mt-5 rounded-xl border border-slate-200 p-4"><summary className="cursor-pointer font-semibold">{t("requirements.summary", { count: value.items.length, hours: value.items.reduce((total, item) => total + item.effort_hours, 0) })}</summary><div className="mt-4 grid gap-3 sm:grid-cols-2">{value.items.map((item) => <article key={item.id} className="rounded-xl border border-slate-200 p-4"><h4 className="font-semibold">{skillNames[item.skill_id] ?? item.skill_id}</h4><p className="mt-2 text-sm text-slate-600">{weekLabels[item.project_week_id] ?? item.project_week_id} · {t("requirements.levelEffort", { level: item.minimum_level, hours: item.effort_hours })}</p></article>)}</div></details>}
    {value.incomplete_items.length ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-semibold">{t("requirements.incomplete")}</h4><ul className="mt-2 list-disc pl-5">{value.incomplete_items.map((item) => <li key={item.task_id}>{taskNames[item.task_id] ?? item.task_id}</li>)}</ul></div> : null}
    {error ? <p role="alert" className="error-message mt-4">{error}</p> : null}
    {feedbackWarning ? <p role="alert" className="mt-4 text-sm text-amber-800">{feedbackWarning}</p> : null}
    {canManage && !editing ? <button className="primary-button mt-5" disabled={submitting || value.incomplete_items.length > 0 || value.status === "STALE" || value.status === "CONFIRMED"} type="button" onClick={() => void mutate(() => confirmRequirements(projectId, value.version, idempotencyKey({ action: "confirm", version: value.version })))}>{t("actions.confirm")}</button> : null}
    {value.status === "STALE" && canManage ? <button className="secondary-button mt-5 ml-3" type="button" onClick={() => void mutate(() => refreshRequirements(projectId, value.version, idempotencyKey({ action: "refresh", version: value.version })))}>{t("actions.refresh")}</button> : null}
    {value.status === "CONFIRMED" && canManage && !recommendation ? <button className="primary-button mt-5 ml-3" disabled={submitting} type="button" onClick={() => void startRecommendation(value)}>{t("recommendation.create")}</button> : null}
    {recommendation ? <>
      <RecommendationCard recommendation={recommendation} canManage={canManage} onEdit={() => setEditingRecommendation(true)} onApprove={() => setDecisionAction("approve")} onReject={() => setDecisionAction("reject")} />
      {staleRecommendation ? <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-4" role="alert"><p>{t("recommendationStaleNotice", { version: staleRecommendation.version })}</p><button className="secondary-button mt-3" type="button" onClick={() => {
        setRecommendationHistory((current) => current.some((item) => item.version === recommendation.version) ? current : [...current, recommendation]);
        setRecommendation(staleRecommendation);
        setStaleRecommendation(null);
      }}>{t("recommendationReapply", { version: staleRecommendation.version })}</button></div> : null}
      {editingRecommendation ? <RecommendationEditor key={recommendation.version} recommendation={recommendation} initialOverrides={pendingOverrides} submitting={submitting} onCancel={() => { setEditingRecommendation(false); setPendingOverrides(undefined); setStaleRecommendation(null); }} onSave={(overrides) => void saveRecommendation(overrides)} /> : null}
      {decisionAction ? <section className="mt-5 rounded-xl border border-slate-300 p-5" aria-labelledby="team-decision-title">
        <h3 className="font-semibold" id="team-decision-title">{decisionAction === "approve" ? t("teamDecisionApproveTitle") : t("teamDecisionRejectTitle")}</h3>
        <p className="mt-2 text-sm text-slate-600">{decisionAction === "approve" ? t("teamDecisionApprovalBoundary") : t("teamDecisionRejectHint")}</p>
        <label className="field-label mt-4">{t("teamDecisionNote")}<textarea className="field-input" maxLength={500} value={decisionNote} onChange={(event) => { setDecisionNote(event.target.value); setDecisionValidation(null); }} /></label>
        {decisionValidation ? <p className="error-message mt-3" role="alert">{decisionValidation}</p> : null}
        <div className="mt-4 flex gap-3"><button className="primary-button" disabled={submitting} type="button" onClick={() => void decide()}>{decisionAction === "approve" ? t("teamDecisionConfirmApprove") : t("teamDecisionConfirmReject")}</button><button className="secondary-button" disabled={submitting} type="button" onClick={() => { setDecisionAction(null); setDecisionValidation(null); }}>{t("teamDecisionCancel")}</button></div>
      </section> : null}
      <RecommendationHistory current={recommendation} previous={recommendationHistory} />
    </> : null}
    {team.data ? <CurrentTeam team={team.data} memberNames={Object.fromEntries((recommendation?.alternatives ?? []).map((candidate) => [candidate.membership_id, candidate.display_name]))} /> : null}
    {preview.data?.requirement_set_id === value.id && preview.data.requirement_version === value.version ? <RankingPreviewView preview={preview.data} requirementLabels={requirementLabels} openableEvidenceTaskIds={new Set((tasks.data ?? []).map((task) => task.id))} onOpenEvidenceTask={onOpenTask ? (taskId) => { const task = tasks.data?.find((item) => item.id === taskId); if (task) onOpenTask(task); } : undefined} /> : preview.isPending ? <p className="mt-8" role="status">{t("ranking.loading")}</p> : <p className="mt-8 text-sm text-slate-600">{t("ranking.unavailable")}</p>}
  </section>;
}
