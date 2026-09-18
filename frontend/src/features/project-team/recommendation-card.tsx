"use client";

import { useTranslations } from "next-intl";

import type { CandidateRanking, RecommendationVersion } from "./contracts";

type Props = {
  recommendation: RecommendationVersion;
  canManage?: boolean;
  onEdit?: () => void;
  onApprove?: () => void;
  onReject?: () => void;
};

export function RecommendationCard({ recommendation, canManage = false, onEdit, onApprove, onReject }: Props) {
  const t = useTranslations("projectTeam.recommendation");
  const candidates = new Map(recommendation.alternatives.map((candidate) => [candidateKey(candidate.requirement_id, candidate.membership_id), candidate]));
  const uncoveredHours = recommendation.uncovered.reduce((total, item) => total + Number(item.uncovered_effort_hours), 0);
  const actionable = canManage && recommendation.status === "PROPOSED";

  return <article className="mt-8 rounded-xl border border-slate-200 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 className="text-xl font-semibold">{t("version", { version: recommendation.version })}</h3>
        <p className="mt-1 text-sm text-slate-600">{t("summary", { members: new Set(recommendation.selections.map((selection) => selection.membership_id)).size, hours: uncoveredHours })}</p>
      </div>
      <span className="status-pill">{t(`status.${recommendation.status}`)}</span>
    </div>
    <ul className="mt-4 grid gap-3 sm:grid-cols-2">
      {recommendation.selections.map((selection) => {
        const candidate = candidates.get(candidateKey(selection.requirement_id, selection.membership_id));
        return <li className="rounded-xl border border-slate-200 p-4" key={`${selection.requirement_id}-${selection.membership_id}`}>
          <strong>{candidate?.display_name ?? selection.membership_id}</strong>
          <p className="mt-1 text-sm text-slate-600">{t("allocated", { hours: selection.allocated_effort_hours })}</p>
          {selection.warning_codes.map((warning) => <p className="mt-2 text-sm text-amber-700" key={warning}>{warningLabel(warning, t)}</p>)}
          {selection.override_reason ? <p className="mt-2 text-sm">{t("overrideReason", { reason: selection.override_reason })}</p> : null}
        </li>;
      })}
    </ul>
    <details className="mt-4 rounded-xl bg-slate-50 p-4">
      <summary className="cursor-pointer font-semibold">{t("details")}</summary>
      <p className="mt-3 text-sm text-slate-600">{t(`explanation.${recommendation.explanation_status}`)}</p>
      <div className="mt-4 grid gap-4">
        {recommendation.selections.map((selection) => {
          const candidate = candidates.get(candidateKey(selection.requirement_id, selection.membership_id));
          return candidate ? <CandidateDetails candidate={candidate} key={`${selection.requirement_id}-${selection.membership_id}`} /> : null;
        })}
      </div>
    </details>
    {actionable ? <div className="mt-5 flex flex-wrap gap-3">
      <button className="secondary-button" type="button" onClick={onEdit}>{t("actions.edit")}</button>
      <button className="primary-button" type="button" onClick={onApprove}>{t("actions.approve")}</button>
      <button className="secondary-button" type="button" onClick={onReject}>{t("actions.reject")}</button>
    </div> : null}
  </article>;
}

function CandidateDetails({ candidate }: { candidate: CandidateRanking }) {
  const t = useTranslations("projectTeam.recommendation");
  return <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label={candidate.display_name}>
    <div className="flex items-center justify-between gap-3"><strong>{candidate.display_name}</strong><strong>{candidate.total_points}</strong></div>
    <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
      <Score label={t("scores.skill")} value={candidate.skill_points} />
      <Score label={t("scores.capacity")} value={candidate.capacity_points} />
      <Score label={t("scores.evidence")} value={candidate.evidence_points} />
      <Score label={t("scores.familiarity")} value={candidate.familiarity_points} />
    </dl>
    {candidate.residual_capacity_hours === null ? <p className="mt-3 text-sm text-amber-700">{t("capacityUnknown")}</p> : <p className="mt-3 text-sm text-slate-600">{t("capacityRemaining", { hours: candidate.residual_capacity_hours })}</p>}
    {candidate.evidence.length ? <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">{candidate.evidence.map((evidence) => <li key={evidence.id}>{evidence.summary}</li>)}</ul> : <p className="mt-3 text-sm text-slate-500">{t("noEvidence")}</p>}
  </section>;
}

function Score({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-semibold">{value}</dd></div>;
}

function warningLabel(code: string, t: (key: string) => string) {
  return code === "LOWER_RANKED_CANDIDATE" || code === "CAPACITY_EXCEEDED" || code === "CAPACITY_UNKNOWN"
    ? t(`warnings.${code}`)
    : t("warnings.UNKNOWN");
}

function candidateKey(requirementId: string, membershipId: string) {
  return `${requirementId}:${membershipId}`;
}
