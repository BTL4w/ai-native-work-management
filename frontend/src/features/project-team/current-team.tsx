"use client";

import { useTranslations } from "next-intl";

import type { ProjectTeam } from "./contracts";

export function CurrentTeam({ team, memberNames }: { team: ProjectTeam; memberNames: Record<string, string> }) {
  const t = useTranslations("projectTeam");
  const active = team.memberships.filter((membership) => membership.active);
  if (active.length === 0) return null;
  return <section className="mt-8 rounded-xl border border-emerald-200 bg-emerald-50 p-5" aria-labelledby="current-team-title">
    <h3 className="text-xl font-semibold" id="current-team-title">{t("currentTeamTitle")}</h3>
    <ul className="mt-3 flex flex-wrap gap-2">{active.map((membership) => <li className="status-pill" key={membership.id}>{memberNames[membership.membership_id] ?? <span className="flex flex-col"><span>{t("currentTeamUnknownMember")}</span><span className="font-mono text-xs">{membership.membership_id}</span></span>}</li>)}</ul>
    <p className="mt-4 text-sm text-slate-700">{t("currentTeamNoAssignments")}</p>
  </section>;
}
