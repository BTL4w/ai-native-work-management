"use client";

import { useTranslations } from "next-intl";

import type { RecommendationVersion } from "./contracts";

export function RecommendationHistory({ current, previous }: { current: RecommendationVersion; previous: RecommendationVersion[] }) {
  const t = useTranslations("projectTeam.recommendation.history");
  const projectTeam = useTranslations("projectTeam");
  if (previous.length === 0 && !current.diff) return null;
  const names = new Map([...previous, current].flatMap((version) => version.alternatives.map((candidate) => [candidate.membership_id, candidate.display_name] as const)));
  return <section className="mt-5 rounded-xl border border-slate-200 p-4" aria-labelledby="recommendation-history-title">
    <h3 className="font-semibold" id="recommendation-history-title">{t("title")}</h3>
    {current.diff ? <p className="mt-3 text-sm">{diffLabel(current, names, t)}</p> : null}
    <ul className="mt-3 space-y-2 text-sm">
      {previous.slice().reverse().map((version) => <li className="rounded-lg bg-slate-50 p-3" key={version.version}>
        <strong>{t("readOnly", { version: version.version })}</strong>
        <p className="mt-1">{projectTeam("recommendationHistoryMembers", { names: version.selections.map((selection) => version.alternatives.find((candidate) => candidate.membership_id === selection.membership_id)?.display_name ?? selection.membership_id).join(", ") })}</p>
      </li>)}
    </ul>
  </section>;
}

function diffLabel(current: RecommendationVersion, names: Map<string, string>, t: (key: string, values?: Record<string, string>) => string) {
  const removed = current.diff?.removed_membership_ids.map((id) => names.get(id) ?? id).join(", ") ?? "";
  const added = current.diff?.added_membership_ids.map((id) => names.get(id) ?? id).join(", ") ?? "";
  return removed && added ? t("replaced", { before: removed, after: added })
    : added ? t("added", { names: added })
      : removed ? t("removed", { names: removed })
        : t("membersUnchanged");
}
