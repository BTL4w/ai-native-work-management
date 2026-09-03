"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ZodError } from "zod";

import { listMembers } from "@/features/work/api";
import type { Member } from "@/features/work/contracts";
import { ApiError, isDefinitiveMutationRejection } from "@/shared/api/client";

import {
  deletePersonSkill,
  listPersonSkills,
  listSkills,
  listWorkOutcomeEvidence,
  setPersonSkill,
} from "./api";
import type { PersonSkill, Skill, WorkOutcomeEvidence } from "./contracts";

export const peopleCapacityKeys = {
  scope: (organizationId: string, actorMembershipId: string) =>
    ["people-capacity", organizationId, actorMembershipId] as const,
};

type PersonRecord = Member & { personSkills: PersonSkill[]; workEvidence: WorkOutcomeEvidence[] };
type PeopleCapacityData = { skills: Skill[]; people: PersonRecord[] };
type EditorState = { memberId: string; personSkill?: PersonSkill };
type MutationAttempt = { fingerprint: string; key: string };

function mutationKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

function useMutationAttempt() {
  const attempt = useRef<MutationAttempt | null>(null);
  return {
    keyFor(payload: unknown) {
      const fingerprint = JSON.stringify(payload);
      if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: mutationKey() };
      return attempt.current.key;
    },
    reset() { attempt.current = null; },
  };
}

async function loadPeopleCapacity(actorMember: Member, canManage: boolean): Promise<PeopleCapacityData> {
  if (!canManage) {
    const [skills, personSkills, workEvidence] = await Promise.all([
      listSkills(),
      listPersonSkills(actorMember.membership_id),
      listWorkOutcomeEvidence(actorMember.membership_id),
    ]);
    return { skills, people: [{ ...actorMember, personSkills, workEvidence }] };
  }
  const firstPage = await listMembers();
  const remainingPages = await Promise.all(
    Array.from({ length: Math.max(0, Math.ceil(firstPage.total / firstPage.page_size) - 1) }, (_, index) => listMembers(index + 2)),
  );
  const members = [firstPage, ...remainingPages].flatMap((page) => page.items);
  const [skills, people] = await Promise.all([
    listSkills(),
    Promise.all(members.map(async (member) => {
      const [personSkills, workEvidence] = await Promise.all([
        listPersonSkills(member.membership_id),
        listWorkOutcomeEvidence(member.membership_id),
      ]);
      return { ...member, personSkills, workEvidence };
    })),
  ]);
  return { skills, people };
}

export function PeopleCapacityPanel({
  organizationId,
  actorMembershipId,
  actorMember,
  canManage,
}: {
  organizationId: string;
  actorMembershipId: string;
  actorMember: Member;
  canManage: boolean;
}) {
  const t = useTranslations("people");
  const queryClient = useQueryClient();
  const queryKey = peopleCapacityKeys.scope(organizationId, actorMembershipId);
  const people = useQuery({ queryKey, queryFn: () => loadPeopleCapacity(actorMember, canManage), retry: false });
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [error, setError] = useState<unknown>(null);
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const deleteAttempt = useRef<MutationAttempt | null>(null);

  function openEditor(state: EditorState, trigger: HTMLButtonElement) {
    editorTrigger.current = trigger;
    setEditor(state);
  }

  function closeEditor() {
    editorTrigger.current?.focus();
    setEditor(null);
  }

  function replacePersonSkill(memberId: string, updated: PersonSkill | null, removedSkillId?: string) {
    queryClient.setQueryData<PeopleCapacityData>(queryKey, (previous) => previous && {
      ...previous,
      people: previous.people.map((person) => person.membership_id !== memberId ? person : {
        ...person,
        personSkills: updated === null
          ? person.personSkills.filter((item) => item.skill_id !== removedSkillId)
          : [...person.personSkills.filter((item) => item.skill_id !== updated.skill_id), updated],
      }),
    });
  }

  async function removeSkill(memberId: string, personSkill: PersonSkill) {
    const fingerprint = JSON.stringify({ memberId, skillId: personSkill.skill_id, version: personSkill.version });
    if (deleteAttempt.current?.fingerprint !== fingerprint) {
      deleteAttempt.current = { fingerprint, key: mutationKey() };
    }
    setError(null);
    try {
      await deletePersonSkill(memberId, personSkill.skill_id, personSkill.version, deleteAttempt.current.key);
      deleteAttempt.current = null;
      replacePersonSkill(memberId, null, personSkill.skill_id);
    } catch (caught) {
      setError(caught);
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        await people.refetch();
      }
      if (isDefinitiveMutationRejection(caught)) deleteAttempt.current = null;
    }
  }

  if (people.isPending) return <section className="people-capacity-panel" aria-busy="true"><p role="status">{t("loading")}</p></section>;
  if (people.error) return <section className="people-capacity-panel"><p role="alert">{t("error.load")}</p><button className="secondary-button" type="button" onClick={() => void people.refetch()}>{t("action.reload")}</button></section>;
  const data = people.data;
  if (!data) return null;

  return <section className="people-capacity-panel work-view" aria-labelledby="people-capacity-title">
    <div className="work-view-heading flex flex-wrap items-center justify-between gap-4">
      <div><p className="eyebrow">{t("eyebrow")}</p><h2 className="page-title" id="people-capacity-title">{t("title")}</h2><p className="mt-3 text-slate-600">{t("description")}</p></div>
      {canManage ? <button className="primary-button" disabled={data.people.length === 0 || !data.skills.some((skill) => skill.active)} type="button" onClick={(event) => openEditor({ memberId: data.people[0]?.membership_id ?? actorMembershipId }, event.currentTarget)}>{t("action.add")}</button> : null}
    </div>
    {error ? <div className="people-safe-error" role="alert"><p>{error instanceof ApiError && error.code === "RESOURCE_VERSION_MISMATCH" ? t("error.stale") : t("error.mutation")}</p>{error instanceof ApiError && error.code === "RESOURCE_VERSION_MISMATCH" ? <button className="text-button" type="button" onClick={() => void people.refetch()}>{t("action.reload")}</button> : null}</div> : null}
    {data.people.length === 0 ? <p className="people-empty">{t("empty")}</p> : <div className="people-list">{data.people.map((person) => <PersonCard
      canManage={canManage}
      key={person.membership_id}
      person={person}
      skills={data.skills}
      verifierName={(id) => data.people.find((member) => member.membership_id === id)?.display_name ?? t("memberReference", { id })}
      onEdit={(personSkill, trigger) => openEditor({ memberId: person.membership_id, personSkill }, trigger)}
      onDelete={(personSkill) => void removeSkill(person.membership_id, personSkill)}
    />)}</div>}
    {editor ? <SkillEditor
      actorMembershipId={actorMembershipId}
      members={data.people}
      skills={data.skills}
      state={editor}
      onClose={closeEditor}
      onSaved={(memberId, saved) => { replacePersonSkill(memberId, saved); closeEditor(); }}
      onStale={async (memberId, skillId) => {
        const refreshed = await people.refetch();
        return refreshed.data?.people.find((person) => person.membership_id === memberId)
          ?.personSkills.find((personSkill) => personSkill.skill_id === skillId);
      }}
    /> : null}
  </section>;
}

function PersonCard({ canManage, person, skills, verifierName, onEdit, onDelete }: {
  canManage: boolean;
  person: PersonRecord;
  skills: Skill[];
  verifierName: (membershipId: string) => string;
  onEdit: (personSkill: PersonSkill, trigger: HTMLButtonElement) => void;
  onDelete: (personSkill: PersonSkill) => void;
}) {
  const t = useTranslations("people");
  const skillName = (skillId: string) => skills.find((skill) => skill.id === skillId)?.name ?? t("unknownSkill");
  const activePersonSkills = person.personSkills.filter((item) => item.active);
  return <article className="people-card">
    <header><div><h3>{person.display_name}</h3><p>{t(`role.${person.role}`)}</p></div></header>
    <section aria-label={t("skillsLabel", { name: person.display_name })}>
      <h4>{t("skills")}</h4>
      {activePersonSkills.length === 0 ? <p className="people-empty">{t("noSkills")}</p> : <ul className="people-skill-list">{activePersonSkills.map((item) => <li key={item.id}>
        <div><strong>{skillName(item.skill_id)}</strong><span>{t("level", { level: item.level })}</span><span>{t("verifiedBy", { name: verifierName(item.verified_by_membership_id) })}</span></div>
        <ul className="people-evidence-list">{item.evidence.map((evidence) => <li key={evidence.id}><strong>{evidence.summary}</strong><span>{t("skillEvidenceProvenance", { type: evidence.source_resource_type, sourceId: evidence.source_resource_id, occurredAt: evidence.occurred_at, recorderId: evidence.created_by_membership_id })}</span></li>)}</ul>
        {canManage ? <div className="people-skill-actions"><button aria-label={t("action.editSkill", { skill: skillName(item.skill_id), name: person.display_name })} className="text-button" type="button" onClick={(event) => onEdit(item, event.currentTarget)}>{t("action.edit")}</button><button aria-label={t("action.deleteSkill", { skill: skillName(item.skill_id), name: person.display_name })} className="text-button" type="button" onClick={() => onDelete(item)}>{t("action.delete")}</button></div> : null}
      </li>)}</ul>}
    </section>
    <section aria-label={t("workEvidenceLabel", { name: person.display_name })}>
      <h4>{t("workEvidence")}</h4>
      {person.workEvidence.length === 0 ? <p className="people-empty">{t("noWorkEvidence")}</p> : <ul className="people-evidence-list">{person.workEvidence.map((evidence) => <li key={evidence.id}><strong>{evidence.summary}</strong><span>{t("workEvidenceProvenance", { type: evidence.source_resource_type, sourceId: evidence.source_resource_id, version: evidence.source_resource_version, observedAt: evidence.observed_at, recorderId: evidence.created_by_membership_id })}</span></li>)}</ul>}
    </section>
  </article>;
}

type EditorField = "member" | "skill" | "level" | "evidence";
type EditorFieldErrors = Partial<Record<EditorField, string>>;
type EvidenceAttempt = { fingerprint: string; occurredAt: string };

function SkillEditor({ actorMembershipId, members, skills, state, onClose, onSaved, onStale }: {
  actorMembershipId: string;
  members: PersonRecord[];
  skills: Skill[];
  state: EditorState;
  onClose: () => void;
  onSaved: (memberId: string, personSkill: PersonSkill) => void;
  onStale: (memberId: string, skillId: string) => Promise<PersonSkill | undefined>;
}) {
  const t = useTranslations("people");
  const attempt = useMutationAttempt();
  const [personSkill, setEditedPersonSkill] = useState(state.personSkill);
  const [memberId, setMemberId] = useState(state.memberId);
  const [skillId, setSkillId] = useState(state.personSkill?.skill_id ?? "");
  const [level, setLevel] = useState(String(state.personSkill?.level ?? 1));
  const [evidence, setEvidence] = useState("");
  const [fieldErrors, setFieldErrors] = useState<EditorFieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dialog = useRef<HTMLFormElement>(null);
  const memberField = useRef<HTMLSelectElement>(null);
  const levelField = useRef<HTMLSelectElement>(null);
  const evidenceAttempt = useRef<EvidenceAttempt | null>(null);
  const isEditing = personSkill !== undefined;

  useEffect(() => {
    (isEditing ? levelField.current : memberField.current)?.focus();
  }, [isEditing]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  function messageForField(field: EditorField) {
    if (field === "level") return t("error.level");
    if (field === "evidence") return t("error.invalid");
    return t("error.required");
  }

  function apiFieldErrors(error: ApiError): EditorFieldErrors {
    return error.fieldErrors.reduce<EditorFieldErrors>((result, item) => {
      const field = item.field === "membership_id" ? "member"
        : item.field === "skill_id" ? "skill"
        : item.field === "level" ? "level"
        : item.field.startsWith("evidence") ? "evidence"
        : null;
      if (field) result[field] = messageForField(field);
      return result;
    }, {});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!memberId || !skillId) {
      setFieldErrors({ ...(memberId ? {} : { member: t("error.required") }), ...(skillId ? {} : { skill: t("error.required") }) });
      return;
    }
    const numericLevel = Number(level);
    if (!Number.isInteger(numericLevel) || numericLevel < 1 || numericLevel > 5) { setFieldErrors({ level: t("error.level") }); return; }
    const evidenceSummary = evidence.trim();
    const evidenceFingerprint = JSON.stringify({ memberId, skillId, level: numericLevel, evidence: evidenceSummary });
    if (evidenceAttempt.current?.fingerprint !== evidenceFingerprint) {
      evidenceAttempt.current = { fingerprint: evidenceFingerprint, occurredAt: new Date().toISOString() };
    }
    const payload = {
      skill_id: skillId,
      level: numericLevel,
      evidence: evidenceSummary ? [{
        evidence_type: "MANAGER_NOTE" as const,
        summary: evidenceSummary,
        source_resource_type: "manager_note",
        source_resource_id: actorMembershipId,
        occurred_at: evidenceAttempt.current.occurredAt,
      }] : [],
    };
    setSubmitting(true); setFieldErrors({}); setFormError(null);
    try {
      const result = await setPersonSkill(memberId, skillId, payload, personSkill?.version, attempt.keyFor({ memberId, ...payload, version: personSkill?.version }));
      attempt.reset(); evidenceAttempt.current = null; onSaved(memberId, result.data);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        const refreshed = await onStale(memberId, skillId);
        if (refreshed) setEditedPersonSkill(refreshed);
        setFormError(t("error.stale"));
      } else {
        const mapped = caught instanceof ApiError
          ? apiFieldErrors(caught)
          : caught instanceof ZodError
          ? caught.issues.reduce<EditorFieldErrors>((result, issue) => {
            const field = issue.path[0] === "evidence" ? "evidence" : issue.path[0] === "level" ? "level" : null;
            if (field) result[field] = messageForField(field);
            return result;
          }, {})
          : {};
        if (Object.keys(mapped).length) setFieldErrors(mapped);
        else setFormError(t("error.mutation"));
        if (isDefinitiveMutationRejection(caught)) {
          attempt.reset();
          evidenceAttempt.current = null;
        }
      }
    } finally { setSubmitting(false); }
  }

  return <div className="work-dialog-backdrop" role="presentation"><form ref={dialog} aria-labelledby="people-skill-editor-title" aria-modal="true" className="work-dialog people-skill-editor" onSubmit={submit} role="dialog" tabIndex={-1}>
    <h2 id="people-skill-editor-title">{isEditing ? t("editor.editTitle") : t("editor.addTitle")}</h2>
    <label>{t("editor.member")}<select aria-describedby={fieldErrors.member ? "people-skill-member-error" : undefined} aria-invalid={Boolean(fieldErrors.member)} aria-label={t("editor.member")} className="form-input" disabled={submitting || isEditing} ref={memberField} value={memberId} onChange={(event) => setMemberId(event.target.value)}>{members.map((member) => <option key={member.membership_id} value={member.membership_id}>{member.display_name}</option>)}</select></label>
    {fieldErrors.member ? <p id="people-skill-member-error" role="alert">{fieldErrors.member}</p> : null}
    <label>{t("editor.skill")}<select aria-describedby={fieldErrors.skill ? "people-skill-skill-error" : undefined} aria-invalid={Boolean(fieldErrors.skill)} aria-label={t("editor.skill")} className="form-input" value={skillId} onChange={(event) => setSkillId(event.target.value)} disabled={submitting || isEditing}><option value="">{t("editor.selectSkill")}</option>{skills.filter((skill) => skill.active).map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}</select></label>
    {fieldErrors.skill ? <p id="people-skill-skill-error" role="alert">{fieldErrors.skill}</p> : null}
    <label>{t("editor.level")}<select aria-describedby={fieldErrors.level ? "people-skill-level-error" : undefined} aria-invalid={Boolean(fieldErrors.level)} aria-label={t("editor.level")} className="form-input" ref={levelField} value={level} onChange={(event) => setLevel(event.target.value)} disabled={submitting}>{[1, 2, 3, 4, 5].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    {fieldErrors.level ? <p id="people-skill-level-error" role="alert">{fieldErrors.level}</p> : null}
    <label>{t("editor.evidence")}<textarea aria-describedby={fieldErrors.evidence ? "people-skill-evidence-error" : undefined} aria-invalid={Boolean(fieldErrors.evidence)} aria-label={t("editor.evidence")} className="form-input" value={evidence} onChange={(event) => setEvidence(event.target.value)} disabled={submitting} /></label>
    {fieldErrors.evidence ? <p id="people-skill-evidence-error" role="alert">{fieldErrors.evidence}</p> : null}
    <p className="people-editor-hint">{t("editor.evidenceHint")}</p>
    {formError ? <p role="alert">{formError}</p> : null}
    <div className="work-dialog-actions"><button className="secondary-button" type="button" onClick={onClose} disabled={submitting}>{t("action.cancel")}</button><button className="primary-button" type="submit" disabled={submitting}>{submitting ? t("saving") : t("action.save")}</button></div>
  </form></div>;
}
