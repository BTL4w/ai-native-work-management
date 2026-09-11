"use client";

import { useTranslations } from "next-intl";

import type { RankingPreview } from "./contracts";

export function RankingPreviewView({ preview, requirementLabels, onOpenEvidenceTask, openableEvidenceTaskIds }: { preview: RankingPreview; requirementLabels: Record<string, string>; onOpenEvidenceTask?: (taskId: string) => void; openableEvidenceTaskIds?: ReadonlySet<string> }) {
  const t = useTranslations("projectTeam");
  return <section className="mt-8" aria-labelledby="ranking-title">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">{t("ranking.origin")}</p><h3 id="ranking-title" className="text-xl font-semibold">{t("ranking.title")}</h3></div><span className="status-pill">{preview.policy_version}</span></div>
    {preview.candidates.length === 0 ? <p className="mt-4 text-sm text-slate-600">{t("ranking.empty")}</p> : <div className="mt-5 grid gap-4">
      {preview.candidates.map((candidate) => <article key={`${candidate.requirement_id}-${candidate.membership_id}`} className="rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap justify-between gap-3"><div><h4 className="font-semibold">{candidate.display_name}</h4><p className="mt-1 text-sm text-slate-600">{requirementLabels[candidate.requirement_id] ?? candidate.requirement_id}</p></div><strong>{candidate.total_points}</strong></div>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Score label={t("ranking.skill")} value={candidate.skill_points} /><Score label={t("ranking.capacity")} value={candidate.capacity_points} /><Score label={t("ranking.evidence")} value={candidate.evidence_points} /><Score label={t("ranking.familiarity")} value={candidate.familiarity_points} />
        </dl>
        {candidate.effective_capacity_hours === null ? <p className="mt-3 text-sm text-amber-700">{t("ranking.unknownCapacity")}</p> : <p className="mt-3 text-sm text-slate-600">{t("ranking.capacityValue", { hours: candidate.residual_capacity_hours ?? 0 })}</p>}
        {candidate.hard_failure_codes.length ? <ul className="mt-3 space-y-1 text-sm text-red-700">{candidate.hard_failure_codes.map((code) => <li key={code}>{failureLabel(code, t)}</li>)}</ul> : null}
        {candidate.evidence.length ? <ul className="mt-3 space-y-1 text-sm">{candidate.evidence.map((evidence) => <li key={evidence.id}>{evidence.source_resource_type === "task" && onOpenEvidenceTask && openableEvidenceTaskIds?.has(evidence.source_resource_id) ? <button className="text-button" type="button" onClick={() => onOpenEvidenceTask(evidence.source_resource_id)}>{evidence.summary}</button> : <span>{evidence.summary}</span>}</li>)}</ul> : null}
      </article>)}
    </div>}
    {preview.uncovered.length ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-semibold">{t("ranking.uncovered")}</h4><ul className="mt-2 space-y-1 text-sm">{preview.uncovered.map((item) => <li key={item.requirement_id}>{requirementLabels[item.requirement_id] ?? item.requirement_id}: {t("ranking.uncoveredHours", { hours: item.uncovered_effort_hours })}</li>)}</ul></div> : null}
  </section>;
}

function Score({ label, value }: { label: string; value: string }) { return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-semibold">{value}</dd></div>; }

function failureLabel(code: string, t: (key: string) => string) {
  const known = new Set(["INACTIVE_MEMBER", "CROSS_TENANT", "POLICY_DENIED", "SKILL_MISSING", "SKILL_BELOW_MINIMUM", "WEEKLY_WORKLOAD_MISSING", "NO_RESIDUAL_CAPACITY"]);
  return known.has(code) ? t(`ranking.failures.${code}`) : t("ranking.unknownFailure");
}
