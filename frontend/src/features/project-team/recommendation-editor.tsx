"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { CandidateOverrideInput, RecommendationVersion } from "./contracts";

type Choice = { membershipId: string; reason: string; effort: string };
type Row = { key: string; requirementId: string; choice: Choice };

export function RecommendationEditor({ recommendation, initialOverrides, submitting, onCancel, onSave }: {
  recommendation: RecommendationVersion;
  initialOverrides?: CandidateOverrideInput[];
  submitting: boolean;
  onCancel: () => void;
  onSave: (overrides: CandidateOverrideInput[]) => void;
}) {
  const t = useTranslations("projectTeam.recommendation.editor");
  const failures = useTranslations("projectTeam.ranking.failures");
  const [rows, setRows] = useState<Row[]>(() => initialRows(recommendation, initialOverrides));
  const [validation, setValidation] = useState<string | null>(null);

  function update(key: string, values: Partial<Choice>) {
    setRows((current) => current.map((row) => row.key === key ? { ...row, choice: { ...row.choice, ...values } } : row));
    setValidation(null);
  }

  function submit() {
    const overrides = rows.map((row) => {
      const { choice } = row;
      const eligible = recommendation.alternatives.filter((candidate) => candidate.requirement_id === row.requirementId && candidate.eligible && candidate.hard_failure_codes.length === 0);
      const selected = eligible.find((candidate) => candidate.membership_id === choice.membershipId);
      const warningExpected = eligible[0]?.membership_id !== choice.membershipId
        || selected?.residual_capacity_hours === null
        || (selected?.residual_capacity_hours !== undefined && Number(choice.effort) > selected.residual_capacity_hours);
      if (!selected) {
        setValidation(t("ineligible"));
        return null;
      }
      if (warningExpected && !choice.reason.trim()) {
        setValidation(t("reasonRequired"));
        return null;
      }
      return {
        requirement_id: row.requirementId,
        selected_membership_id: choice.membershipId,
        override_reason: choice.reason.trim() || null,
        allocated_effort_hours: choice.effort,
      } satisfies CandidateOverrideInput;
    });
    if (overrides.some((value) => value === null)) return;
    onSave(overrides as CandidateOverrideInput[]);
  }

  return <section className="mt-5 rounded-xl border border-slate-300 p-5" aria-labelledby="recommendation-editor-title">
    <h3 className="text-lg font-semibold" id="recommendation-editor-title">{t("title", { version: recommendation.version + 1 })}</h3>
    <div className="mt-4 grid gap-5">
      {rows.map((row, index) => {
        const candidates = recommendation.alternatives.filter((candidate) => candidate.requirement_id === row.requirementId);
        return <fieldset className="rounded-xl bg-slate-50 p-4" key={row.key}>
          <legend className="px-1 font-semibold">{t("requirement", { number: index + 1 })}</legend>
          <label className="field-label">{t("member")}
            <select className="field-input" value={row.choice.membershipId} onChange={(event) => update(row.key, { membershipId: event.target.value })}>
              {candidates.map((candidate) => <option disabled={!candidate.eligible || candidate.hard_failure_codes.length > 0} key={candidate.membership_id} value={candidate.membership_id}>
                {candidate.display_name}{candidate.hard_failure_codes.length ? ` · ${candidate.hard_failure_codes.map((code) => failureLabel(code, failures)).join(", ")}` : ` · ${candidate.total_points}`}
              </option>)}
            </select>
          </label>
          <label className="field-label mt-3">{t("reason")}
            <textarea className="field-input" maxLength={500} value={row.choice.reason} onChange={(event) => update(row.key, { reason: event.target.value })} />
          </label>
        </fieldset>;
      })}
    </div>
    {validation ? <p className="error-message mt-4" role="alert">{validation}</p> : null}
    <div className="mt-5 flex flex-wrap gap-3">
      <button className="primary-button" disabled={submitting} type="button" onClick={submit}>{t("save", { version: recommendation.version + 1 })}</button>
      <button className="secondary-button" disabled={submitting} type="button" onClick={onCancel}>{t("cancel")}</button>
    </div>
  </section>;
}

function initialRows(recommendation: RecommendationVersion, initialOverrides: CandidateOverrideInput[] = []): Row[] {
  const rows: Row[] = recommendation.selections.map((selection, index) => ({
    key: `selected-${index}`,
    requirementId: selection.requirement_id,
    choice: {
      membershipId: selection.membership_id,
      reason: selection.override_reason ?? "",
      effort: selection.allocated_effort_hours,
    },
  }));
  for (const [index, uncovered] of recommendation.uncovered.entries()) {
    const alreadySelected = new Set(rows.filter((row) => row.requirementId === uncovered.requirement_id).map((row) => row.choice.membershipId));
    const candidate = recommendation.alternatives.find((item) => item.requirement_id === uncovered.requirement_id && item.eligible && item.hard_failure_codes.length === 0 && !alreadySelected.has(item.membership_id));
    if (candidate) {
      rows.push({
        key: `uncovered-${index}`,
        requirementId: uncovered.requirement_id,
        choice: { membershipId: candidate.membership_id, reason: "", effort: uncovered.uncovered_effort_hours },
      });
    }
  }
  return rows.map((row) => {
    const override = initialOverrides.find((item) => item.requirement_id === row.requirementId);
    return override ? {
      ...row,
      choice: {
        membershipId: override.selected_membership_id,
        reason: override.override_reason ?? "",
        effort: override.allocated_effort_hours
          ?? recommendation.demands.find((demand) => demand.requirement_id === row.requirementId)?.effort_hours
          ?? row.choice.effort,
      },
    } : row;
  });
}

function failureLabel(code: string, t: (key: string) => string) {
  const known = new Set(["INACTIVE_MEMBER", "CROSS_TENANT", "POLICY_DENIED", "SKILL_MISSING", "SKILL_BELOW_MINIMUM", "WEEKLY_WORKLOAD_MISSING", "NO_RESIDUAL_CAPACITY"]);
  return known.has(code) ? t(code) : code;
}
