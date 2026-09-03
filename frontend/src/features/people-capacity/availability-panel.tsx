"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";

import type { Member } from "@/features/work/contracts";
import { ApiError, isDefinitiveMutationRejection } from "@/shared/api/client";

import {
  createLeave,
  listCapacity,
  listLeave,
  listWeeklyWorkload,
  updateLeave,
  upsertCapacity,
} from "./api";
import type { CapacityEntry, CapacityKind, LeaveEntry, WeeklyWorkload } from "./contracts";

export const availabilityKeys = {
  entries: (organizationId: string, actorMembershipId: string, weekStart: string) =>
    ["people-capacity", organizationId, actorMembershipId, "availability", weekStart] as const,
  workload: (organizationId: string, actorMembershipId: string, weekStart: string) =>
    ["people-capacity", organizationId, actorMembershipId, "workload", weekStart] as const,
};

type AvailabilityData = { capacity: CapacityEntry[]; leave: LeaveEntry[] };
type CapacityEditorState = { type: "capacity"; entry?: CapacityEntry };
type LeaveEditorState = { type: "leave"; entry?: LeaveEntry };
type EditorState = CapacityEditorState | LeaveEditorState;
type MutationAttempt = { fingerprint: string; key: string };

function dateFromIso(value: string) {
  return new Date(`${value}T00:00:00.000Z`);
}

function addDays(value: string, days: number) {
  const date = dateFromIso(value);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function localWeekStart(value = new Date()) {
  const date = new Date(value.getTime());
  const day = date.getDay();
  date.setDate(date.getDate() - (day === 0 ? 6 : day - 1));
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const calendarDay = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${calendarDay}`;
}

function displayDate(value: string) {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function mutationKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function useMutationAttempt() {
  const attempt = useRef<MutationAttempt | null>(null);
  return {
    keyFor(payload: unknown) {
      const fingerprint = JSON.stringify(payload);
      if (attempt.current?.fingerprint !== fingerprint) {
        attempt.current = { fingerprint, key: mutationKey() };
      }
      return attempt.current.key;
    },
    reset() { attempt.current = null; },
  };
}

function useDialogBehavior(onClose: () => void) {
  const dialog = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const focusableSelector = "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";
    dialog.current?.querySelector<HTMLElement>(focusableSelector)?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { onClose(); return; }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(focusableSelector));
      if (focusable.length === 0) { event.preventDefault(); dialog.current.focus(); return; }
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  return dialog;
}

function leaveHoursInWeek(entry: LeaveEntry, weekStart: string, weekEnd: string) {
  const overlapStart = entry.start_date > weekStart ? entry.start_date : weekStart;
  const overlapEnd = entry.end_date < weekEnd ? entry.end_date : weekEnd;
  if (overlapEnd < overlapStart) return 0;
  const millisecondsPerDay = 86_400_000;
  const totalDays = Math.floor((dateFromIso(entry.end_date).getTime() - dateFromIso(entry.start_date).getTime()) / millisecondsPerDay) + 1;
  const overlapDays = Math.floor((dateFromIso(overlapEnd).getTime() - dateFromIso(overlapStart).getTime()) / millisecondsPerDay) + 1;
  const hoursPerDay = Math.floor(entry.unavailable_hours / totalDays);
  const remainder = entry.unavailable_hours % totalDays;
  const remainderEnd = addDays(entry.start_date, remainder - 1);
  const remainderDays = remainder > 0 && overlapStart <= remainderEnd
    ? Math.floor((dateFromIso(overlapEnd < remainderEnd ? overlapEnd : remainderEnd).getTime() - dateFromIso(overlapStart).getTime()) / millisecondsPerDay) + 1
    : 0;
  return hoursPerDay * overlapDays + Math.max(remainderDays, 0);
}

export function AvailabilityPanel({
  organizationId,
  actorMembershipId,
  members,
  canManage,
  initialWeekStart,
}: {
  organizationId: string;
  actorMembershipId: string;
  members: Member[];
  canManage: boolean;
  initialWeekStart?: string;
}) {
  const t = useTranslations("people.availability");
  const [weekStart, setWeekStart] = useState(initialWeekStart ?? localWeekStart);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const weekEnd = addDays(weekStart, 6);
  const membershipFilter = canManage ? undefined : actorMembershipId;
  const availability = useQuery({
    queryKey: availabilityKeys.entries(organizationId, actorMembershipId, weekStart),
    queryFn: async (): Promise<AvailabilityData> => {
      const [capacity, leave] = await Promise.all([
        listCapacity(membershipFilter),
        listLeave({ membershipId: membershipFilter, startDate: weekStart, endDate: weekEnd }),
      ]);
      return { capacity, leave };
    },
    retry: false,
  });
  const workload = useQuery({
    queryKey: availabilityKeys.workload(organizationId, actorMembershipId, weekStart),
    queryFn: () => listWeeklyWorkload(weekStart, membershipFilter),
    retry: false,
  });

  async function refresh() {
    const [availabilityResult] = await Promise.all([availability.refetch(), workload.refetch()]);
    return availabilityResult.data;
  }

  function openEditor(state: EditorState, trigger: HTMLButtonElement) {
    editorTrigger.current = trigger;
    setEditor(state);
  }

  function closeEditor() {
    editorTrigger.current?.focus();
    setEditor(null);
  }

  const isPending = availability.isPending || workload.isPending;
  const loadError = availability.error || workload.error;

  return <section className="availability-panel" aria-labelledby="availability-title">
    <header className="availability-header">
      <div>
        <h3 id="availability-title">{t("title")}</h3>
        <p>{t("description")}</p>
      </div>
      {canManage ? <div className="availability-actions">
        <button className="secondary-button" type="button" onClick={(event) => openEditor({ type: "capacity" }, event.currentTarget)}>{t("action.capacity")}</button>
        <button className="secondary-button" type="button" onClick={(event) => openEditor({ type: "leave" }, event.currentTarget)}>{t("action.leave")}</button>
      </div> : null}
    </header>
    <div className="availability-week-nav">
      <button aria-label={t("previousWeek")} className="text-button" type="button" onClick={() => setWeekStart(addDays(weekStart, -7))}>←</button>
      <strong>{t("weekLabel", { range: `${displayDate(weekStart)} – ${displayDate(weekEnd)}` })}</strong>
      <button aria-label={t("nextWeek")} className="text-button" type="button" onClick={() => setWeekStart(addDays(weekStart, 7))}>→</button>
    </div>
    {isPending ? <p role="status">{t("loading")}</p> : loadError ? <div className="people-safe-error" role="alert"><p>{t("error.load")}</p><button className="text-button" type="button" onClick={() => void refresh()}>{t("action.reload")}</button></div> : <AvailabilityRows
      capacityEntries={availability.data?.capacity ?? []}
      canManage={canManage}
      leaveEntries={availability.data?.leave ?? []}
      members={members}
      onEditCapacity={(entry, trigger) => openEditor({ type: "capacity", entry }, trigger)}
      onEditLeave={(entry, trigger) => openEditor({ type: "leave", entry }, trigger)}
      weekStart={weekStart}
      workloads={workload.data ?? []}
    />}
    {editor?.type === "capacity" ? <CapacityEditor
      entry={editor.entry}
      members={members}
      onClose={closeEditor}
      onStale={async (entryId) => (await refresh())?.capacity.find((entry) => entry.id === entryId)}
      onSaved={async () => { await refresh(); closeEditor(); }}
      weekStart={weekStart}
    /> : null}
    {editor?.type === "leave" ? <LeaveEditor
      entry={editor.entry}
      members={members}
      onClose={closeEditor}
      onStale={async (entryId) => (await refresh())?.leave.find((entry) => entry.id === entryId)}
      onSaved={async () => { await refresh(); closeEditor(); }}
      weekStart={weekStart}
    /> : null}
  </section>;
}

function AvailabilityRows({ capacityEntries, leaveEntries, workloads, members, weekStart, canManage, onEditCapacity, onEditLeave }: {
  capacityEntries: CapacityEntry[];
  leaveEntries: LeaveEntry[];
  workloads: WeeklyWorkload[];
  members: Member[];
  weekStart: string;
  canManage: boolean;
  onEditCapacity: (entry: CapacityEntry, trigger: HTMLButtonElement) => void;
  onEditLeave: (entry: LeaveEntry, trigger: HTMLButtonElement) => void;
}) {
  const t = useTranslations("people.availability");
  const memberName = (membershipId: string) => members.find((member) => member.membership_id === membershipId)?.display_name
    ?? t("memberFallback", { id: membershipId });
  const weekEnd = addDays(weekStart, 6);
  const relevantCapacityEntries = capacityEntries.filter((entry) => entry.kind === "OVERRIDE"
    ? entry.week_start === weekStart
    : entry.effective_from <= weekEnd && entry.effective_to >= weekStart);
  const memberIds = Array.from(new Set([
    ...relevantCapacityEntries.map((entry) => entry.membership_id),
    ...leaveEntries.map((entry) => entry.membership_id),
    ...workloads.map((entry) => entry.membership_id),
  ]));
  if (memberIds.length === 0) return <p className="people-empty">{t("empty")}</p>;

  return <div className="availability-grid">{memberIds.map((membershipId) => {
    const memberWorkloads = workloads.filter((entry) => entry.membership_id === membershipId);
    const memberCapacity = relevantCapacityEntries.filter((entry) => entry.membership_id === membershipId);
    const selectedCapacity = memberCapacity.find((entry) => entry.kind === "OVERRIDE" && entry.week_start === weekStart)
      ?? memberCapacity.find((entry) => entry.kind === "DEFAULT");
    const memberLeave = leaveEntries.filter((entry) => entry.membership_id === membershipId);
    const leaveHours = Math.min(memberLeave.reduce((sum, entry) => sum + leaveHoursInWeek(entry, weekStart, weekEnd), 0), 168);
    const overloaded = memberWorkloads.some((item) => item.allocated_effort_hours > item.effective_capacity_hours);
    return <article className={`availability-card${overloaded ? " is-overloaded" : ""}`} key={membershipId}>
      <header><div><h4>{memberName(membershipId)}</h4><p>{t("capacity", { hours: selectedCapacity?.hours ?? 0 })} · {t("leave", { hours: leaveHours })}</p></div></header>
      {memberWorkloads.length === 0 ? <p className="people-empty">{t("empty")}</p> : <div className="availability-workload-list">{memberWorkloads.map((item) => {
        const ratio = item.workload_ratio === null ? null : Number(item.workload_ratio);
        const percent = ratio === null ? null : Math.round(ratio * 100);
        const ratioText = percent === null ? t("ratioUnavailable") : t("ratio", { percent });
        const overload = Math.max(item.allocated_effort_hours - item.effective_capacity_hours, 0);
        return <section aria-label={t("projectWeek", { id: item.project_week_id })} className="availability-workload" key={item.project_week_id}>
          {memberWorkloads.length > 1 ? <span className="availability-week-reference">{t("projectWeek", { id: item.project_week_id })}</span> : null}
          <div className="availability-allocation"><strong>{t("allocation", { allocated: item.allocated_effort_hours, capacity: item.effective_capacity_hours })}</strong><span>{item.effective_capacity_hours === 0 ? t("zeroCapacity") : overload > 0 ? t("overloaded", { hours: overload }) : t("remaining", { hours: item.residual_capacity_hours })}</span></div>
          <div aria-label={ratioText} aria-valuemax={100} aria-valuemin={0} aria-valuenow={percent === null ? undefined : Math.min(percent, 100)} aria-valuetext={ratioText} className="capacity-rail" role="progressbar"><span style={{ width: `${Math.min(percent ?? 0, 100)}%` }} /></div>
          <p>{ratioText}</p>
        </section>;
      })}</div>}
      {canManage && (memberCapacity.length > 0 || memberLeave.length > 0) ? <ul className="availability-entry-list">
        {memberCapacity.map((entry) => <li key={entry.id}><span>{entry.kind === "DEFAULT" ? t("entryDefault", { hours: entry.hours }) : t("entryOverride", { hours: entry.hours })}</span><button aria-label={t("action.editCapacity", { name: memberName(membershipId) })} className="text-button" type="button" onClick={(event) => onEditCapacity(entry, event.currentTarget)}>{t("action.capacity")}</button></li>)}
        {memberLeave.map((entry) => <li key={entry.id}><span>{t("leaveEntry", { startDate: displayDate(entry.start_date), endDate: displayDate(entry.end_date), hours: entry.unavailable_hours })}</span><button aria-label={t("action.editLeave", { name: memberName(membershipId) })} className="text-button" type="button" onClick={(event) => onEditLeave(entry, event.currentTarget)}>{t("action.leave")}</button></li>)}
      </ul> : null}
    </article>;
  })}</div>;
}

function CapacityEditor({ entry, members, weekStart, onClose, onSaved, onStale }: {
  entry?: CapacityEntry;
  members: Member[];
  weekStart: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
  onStale: (entryId: string) => Promise<CapacityEntry | undefined>;
}) {
  const t = useTranslations("people.availability");
  const attempt = useMutationAttempt();
  const [persistedEntry, setPersistedEntry] = useState(entry);
  const [membershipId, setMembershipId] = useState(persistedEntry?.membership_id ?? members[0]?.membership_id ?? "");
  const [kind, setKind] = useState<CapacityKind>(persistedEntry?.kind ?? "DEFAULT");
  const [hours, setHours] = useState(String(persistedEntry?.hours ?? 40));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dialog = useDialogBehavior(onClose);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const numericHours = Number(hours);
    if (!membershipId || !Number.isInteger(numericHours) || numericHours < 0 || numericHours > 168) { setError(t("error.invalid")); return; }
    const payload = {
      membership_id: membershipId,
      kind,
      hours: numericHours,
      ...(kind === "OVERRIDE" ? { week_start: persistedEntry?.week_start ?? weekStart } : {}),
      ...(persistedEntry ? { effective_from: persistedEntry.effective_from, effective_to: persistedEntry.effective_to } : {}),
    };
    const version = persistedEntry?.version;
    setSubmitting(true); setError(null);
    try {
      await upsertCapacity(payload, version, attempt.keyFor({ ...payload, version }));
      attempt.reset();
      await onSaved();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        const fresh = persistedEntry ? await onStale(persistedEntry.id) : undefined;
        if (fresh) {
          setPersistedEntry(fresh);
          setMembershipId(fresh.membership_id);
          setKind(fresh.kind);
          setHours(String(fresh.hours));
        }
        setError(t("error.stale"));
      } else {
        setError(t("error.mutation"));
        if (isDefinitiveMutationRejection(caught)) attempt.reset();
      }
    } finally { setSubmitting(false); }
  }

  const title = persistedEntry ? t("editor.editCapacity") : t("editor.addCapacity");
  return <div className="work-dialog-backdrop" role="presentation"><form ref={dialog} aria-labelledby="capacity-editor-title" aria-modal="true" className="work-dialog availability-editor" onSubmit={submit} role="dialog" tabIndex={-1}>
    <h2 id="capacity-editor-title">{title}</h2>
    <label>{t("editor.member")}<select aria-label={t("editor.member")} className="form-input" disabled={submitting || Boolean(persistedEntry)} value={membershipId} onChange={(event) => setMembershipId(event.target.value)}>{members.map((member) => <option key={member.membership_id} value={member.membership_id}>{member.display_name}</option>)}</select></label>
    <label>{t("editor.kind")}<select aria-label={t("editor.kind")} className="form-input" disabled={submitting || Boolean(persistedEntry)} value={kind} onChange={(event) => setKind(event.target.value as CapacityKind)}><option value="DEFAULT">{t("editor.defaultKind")}</option><option value="OVERRIDE">{t("editor.overrideKind")}</option></select></label>
    <label>{t("editor.hours")}<input aria-label={t("editor.hours")} className="form-input" disabled={submitting} max={168} min={0} type="number" value={hours} onChange={(event) => setHours(event.target.value)} /></label>
    {error ? <p role="alert">{error}</p> : null}
    <div className="work-dialog-actions"><button className="secondary-button" disabled={submitting} type="button" onClick={onClose}>{t("action.cancel")}</button><button className="primary-button" disabled={submitting} type="submit">{t("action.saveCapacity")}</button></div>
  </form></div>;
}

function LeaveEditor({ entry, members, weekStart, onClose, onSaved, onStale }: {
  entry?: LeaveEntry;
  members: Member[];
  weekStart: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
  onStale: (entryId: string) => Promise<LeaveEntry | undefined>;
}) {
  const t = useTranslations("people.availability");
  const attempt = useMutationAttempt();
  const [persistedEntry, setPersistedEntry] = useState(entry);
  const [membershipId, setMembershipId] = useState(persistedEntry?.membership_id ?? members[0]?.membership_id ?? "");
  const [startDate, setStartDate] = useState(persistedEntry?.start_date ?? weekStart);
  const [endDate, setEndDate] = useState(persistedEntry?.end_date ?? weekStart);
  const [hours, setHours] = useState(String(persistedEntry?.unavailable_hours ?? 8));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dialog = useDialogBehavior(onClose);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const numericHours = Number(hours);
    if (!membershipId || endDate < startDate || !Number.isInteger(numericHours) || numericHours < 0 || numericHours > 168) { setError(t("error.invalid")); return; }
    const payload = { start_date: startDate, end_date: endDate, unavailable_hours: numericHours };
    setSubmitting(true); setError(null);
    try {
      const version = persistedEntry?.version;
      if (persistedEntry && version !== undefined) await updateLeave(persistedEntry.id, payload, version, attempt.keyFor({ id: persistedEntry.id, ...payload, version }));
      else await createLeave({ membership_id: membershipId, ...payload }, attempt.keyFor({ membershipId, ...payload }));
      attempt.reset();
      await onSaved();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        const fresh = persistedEntry ? await onStale(persistedEntry.id) : undefined;
        if (fresh) {
          setPersistedEntry(fresh);
          setMembershipId(fresh.membership_id);
          setStartDate(fresh.start_date);
          setEndDate(fresh.end_date);
          setHours(String(fresh.unavailable_hours));
        }
        setError(t("error.stale"));
      } else {
        setError(t("error.mutation"));
        if (isDefinitiveMutationRejection(caught)) attempt.reset();
      }
    } finally { setSubmitting(false); }
  }

  const title = persistedEntry ? t("editor.editLeave") : t("editor.addLeave");
  return <div className="work-dialog-backdrop" role="presentation"><form ref={dialog} aria-labelledby="leave-editor-title" aria-modal="true" className="work-dialog availability-editor" onSubmit={submit} role="dialog" tabIndex={-1}>
    <h2 id="leave-editor-title">{title}</h2>
    <label>{t("editor.member")}<select aria-label={t("editor.member")} className="form-input" disabled={submitting || Boolean(persistedEntry)} value={membershipId} onChange={(event) => setMembershipId(event.target.value)}>{members.map((member) => <option key={member.membership_id} value={member.membership_id}>{member.display_name}</option>)}</select></label>
    <label>{t("editor.startDate")}<input aria-label={t("editor.startDate")} className="form-input" disabled={submitting} type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
    <label>{t("editor.endDate")}<input aria-label={t("editor.endDate")} className="form-input" disabled={submitting} type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
    <label>{t("editor.leaveHours")}<input aria-label={t("editor.leaveHours")} className="form-input" disabled={submitting} max={168} min={0} type="number" value={hours} onChange={(event) => setHours(event.target.value)} /></label>
    {error ? <p role="alert">{error}</p> : null}
    <div className="work-dialog-actions"><button className="secondary-button" disabled={submitting} type="button" onClick={onClose}>{t("action.cancel")}</button><button className="primary-button" disabled={submitting} type="submit">{t("action.saveLeave")}</button></div>
  </form></div>;
}
