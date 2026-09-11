"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { RequirementItemInput, TeamRequirementSet } from "./contracts";

type Item = TeamRequirementSet["items"][number];
type Option = { id: string; name: string };
type Week = { id: string; label: string };
type Task = { id: string; title: string };

export function RequirementsEditor({ items, skills, weeks, tasks, submitting, onSave, onCancel }: {
  items: Item[]; skills: Option[]; weeks: Week[]; tasks: Task[]; submitting: boolean;
  onSave: (items: RequirementItemInput[]) => void; onCancel: () => void;
}) {
  const t = useTranslations("projectTeam");
  const [rows, setRows] = useState<RequirementItemInput[]>(items.map((item) => ({
    skill_id: item.skill_id,
    minimum_level: item.minimum_level,
    project_week_id: item.project_week_id,
    effort_hours: item.effort_hours,
    source_task_ids: item.source_task_ids,
  })));
  const [error, setError] = useState<string | null>(null);

  function update(index: number, patch: Partial<RequirementItemInput>) {
    setRows((value) => value.map((row, position) => position === index ? { ...row, ...patch } : row));
  }
  function save() {
    const duplicateKeys = rows.map((row) => `${row.skill_id}:${row.project_week_id}`);
    if (new Set(duplicateKeys).size !== duplicateKeys.length) return setError(t("validation.duplicate"));
    if (rows.some((row) => !row.skill_id || !row.project_week_id || row.effort_hours < 1)) return setError(t("validation.required"));
    setError(null);
    onSave(rows);
  }
  function add() {
    const skill = skills[0]?.id;
    const week = weeks[0]?.id;
    if (!skill || !week) return setError(t("validation.references"));
    setRows((value) => [...value, { skill_id: skill, minimum_level: 1, project_week_id: week, effort_hours: 1, source_task_ids: [] }]);
  }

  return <div className="mt-5">
    <div className="grid gap-4">
      {rows.map((row, index) => <fieldset key={`${index}-${row.skill_id}-${row.project_week_id}`} className="rounded-xl border border-slate-200 p-4">
        <legend className="px-2 text-sm font-semibold">{t("requirements.row", { number: index + 1 })}</legend>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm font-medium">{t("fields.skill")}<select className="form-input mt-2" value={row.skill_id} onChange={(event) => update(index, { skill_id: event.target.value })}>{skills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}</select></label>
          <label className="text-sm font-medium">{t("fields.week")}<select className="form-input mt-2" value={row.project_week_id} onChange={(event) => update(index, { project_week_id: event.target.value })}>{weeks.map((week) => <option key={week.id} value={week.id}>{week.label}</option>)}</select></label>
          <label className="text-sm font-medium">{t("fields.level")}<input aria-label={t("fields.level")} className="form-input mt-2" min={1} max={5} type="number" value={row.minimum_level} onChange={(event) => update(index, { minimum_level: Number(event.target.value) })} /></label>
          <label className="text-sm font-medium">{t("fields.effort")}<input aria-label={t("fields.effort")} className="form-input mt-2" min={1} type="number" value={row.effort_hours} onChange={(event) => update(index, { effort_hours: Number(event.target.value) })} /></label>
        </div>
        {tasks.length ? <label className="mt-4 block text-sm font-medium">{t("fields.sourceTasks")}<select multiple className="form-input mt-2 min-h-24" value={row.source_task_ids} onChange={(event) => update(index, { source_task_ids: Array.from(event.target.selectedOptions, (option) => option.value) })}>{tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}</select></label> : null}
        <button className="text-button mt-3" type="button" onClick={() => setRows((value) => value.filter((_item, position) => position !== index))}>{t("actions.remove")}</button>
      </fieldset>)}
    </div>
    {error ? <p className="error-message mt-4" role="alert">{error}</p> : null}
    <div className="mt-5 flex flex-wrap justify-end gap-3"><button className="secondary-button" type="button" onClick={add}>{t("actions.add")}</button><button className="secondary-button" type="button" onClick={onCancel}>{t("actions.cancel")}</button><button className="primary-button" disabled={submitting} type="button" onClick={save}>{t("actions.save")}</button></div>
  </div>;
}
