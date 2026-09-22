"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { getRecommendationVersion } from "@/features/project-team/api";
import type { CandidateOverrideInput, RecommendationVersion } from "@/features/project-team/contracts";
import { RecommendationCard } from "@/features/project-team/recommendation-card";
import { RecommendationEditor } from "@/features/project-team/recommendation-editor";
import { RecommendationHistory } from "@/features/project-team/recommendation-history";

import type { AssistantBlock } from "../contracts";

type Block = Extract<AssistantBlock, { kind: "team_recommendation" }>;

export function TeamRecommendationBlock({
  block,
  canManage,
  isLatest,
  onRequestRevision,
  onManualRevise,
  onDecide,
  onOpenTeam,
}: {
  block: Block;
  canManage: boolean;
  isLatest: boolean;
  onRequestRevision: (block: Block) => void;
  onManualRevise: (recommendation: RecommendationVersion, overrides: CandidateOverrideInput[]) => Promise<RecommendationVersion | null>;
  onDecide: (recommendation: RecommendationVersion, action: "approve" | "reject", reason: string | null) => Promise<RecommendationVersion | null>;
  onOpenTeam?: (projectId: string) => void;
}) {
  const t = useTranslations("assistant.teamRecommendation");
  const query = useQuery({
    queryKey: ["assistant", "team-recommendation", block.recommendation_id, block.recommendation_version],
    queryFn: async () => (await getRecommendationVersion(block.recommendation_id, block.recommendation_version)).data,
    retry: false,
  });
  const [current, setCurrent] = useState<RecommendationVersion | null>(null);
  const [previous, setPrevious] = useState<RecommendationVersion[]>([]);
  const [editing, setEditing] = useState(false);
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);

  if (query.isPending) return <section className="assistant-block" role="status">{t("loading", { version: block.recommendation_version })}</section>;
  if (query.error || (!query.data && !current)) return <section className="assistant-block assistant-safe-error" role="alert">
    <p>{t("unavailable")}</p>
    {onOpenTeam ? <button type="button" onClick={() => onOpenTeam(block.project_id)}>{t("openTeam")}</button> : null}
  </section>;

  const recommendation = current ?? query.data as RecommendationVersion;
  const actionable = canManage && isLatest && block.status === "PROPOSED" && recommendation.status === "PROPOSED";

  async function save(overrides: CandidateOverrideInput[]) {
    setSubmitting(true); setError(false);
    const revised = await onManualRevise(recommendation, overrides);
    setSubmitting(false);
    if (!revised) { setError(true); return; }
    setPrevious((items) => [...items, recommendation]);
    setCurrent(revised); setEditing(false);
  }

  async function confirmDecision() {
    if (!decision) return;
    const normalizedReason = reason.trim() || null;
    if (decision === "reject" && !normalizedReason) { setError(true); return; }
    setSubmitting(true); setError(false);
    const decided = await onDecide(recommendation, decision, normalizedReason);
    setSubmitting(false);
    if (!decided) { setError(true); return; }
    setCurrent(decided); setDecision(null); setReason("");
  }

  return <section className={`assistant-team-recommendation${actionable ? "" : " is-read-only"}`}>
    {!isLatest ? <p className="assistant-stale-notice">{t("readOnly", { version: recommendation.version })}</p> : null}
    <RecommendationCard
      recommendation={recommendation}
      canManage={actionable}
      onEdit={() => setEditing(true)}
      onApprove={() => setDecision("approve")}
      onReject={() => setDecision("reject")}
    />
    {actionable ? <button className="secondary-button mt-3" type="button" onClick={() => onRequestRevision({ ...block, recommendation_version: recommendation.version, status: recommendation.status, explanation_status: recommendation.explanation_status })}>{t("requestRevision")}</button> : null}
    {editing ? <RecommendationEditor recommendation={recommendation} submitting={submitting} onCancel={() => setEditing(false)} onSave={(overrides) => void save(overrides)} /> : null}
    {decision ? <section className="mt-4 rounded-xl border border-slate-200 p-4" aria-labelledby={`team-decision-${block.recommendation_id}-${block.recommendation_version}`}>
      <h3 id={`team-decision-${block.recommendation_id}-${block.recommendation_version}`}>{t(`decision.${decision}.title`)}</h3>
      <p className="mt-2 text-sm text-slate-600">{t(`decision.${decision}.boundary`)}</p>
      <label className="field-label mt-3">{t("decision.reason")}<textarea className="field-input" value={reason} onChange={(event) => { setReason(event.target.value); setError(false); }} /></label>
      {error ? <p className="error-message mt-3" role="alert">{t(decision === "reject" && !reason.trim() ? "decision.reasonRequired" : "mutationFailed")}</p> : null}
      <div className="mt-3 flex gap-3"><button className="primary-button" disabled={submitting} type="button" onClick={() => void confirmDecision()}>{t("decision.confirm")}</button><button className="secondary-button" disabled={submitting} type="button" onClick={() => setDecision(null)}>{t("decision.cancel")}</button></div>
    </section> : null}
    {error && !decision ? <p className="error-message mt-3" role="alert">{t("mutationFailed")}</p> : null}
    <RecommendationHistory current={recommendation} previous={previous} />
  </section>;
}
