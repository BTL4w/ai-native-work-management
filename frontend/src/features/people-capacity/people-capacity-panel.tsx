"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState, type FormEvent } from "react";

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

async function loadPeopleCapacity(): Promise<PeopleCapacityData> {
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
  canManage,
}: {
  organizationId: string;
  actorMembershipId: string;
  canManage: boolean;
}) {
  const t = useTranslations("people");
  const queryClient = useQueryClient();
  const queryKey = peopleCapacityKeys.scope(organizationId, actorMembershipId);
  const people = useQuery({ queryKey, queryFn: loadPeopleCapacity, retry: false });
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [error, setError] = useState<unknown>(null);

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
    const idempotencyKey = mutationKey();
    setError(null);
    try {
      await deletePersonSkill(memberId, personSkill.skill_id, personSkill.version, idempotencyKey);
      replacePersonSkill(memberId, null, personSkill.skill_id);
    } catch (caught) {
      setError(caught);
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        await people.refetch();
      }
    }
  }

  if (people.isPending) return <section className="people-capacity-panel" aria-busy="true"><p role="status">{t("loading")}</p></section>;
  if (people.error) return <section className="people-capacity-panel"><p role="alert">{t("error.load")}</p><button className="secondary-button" type="button" onClick={() => void people.refetch()}>{t("action.reload")}</button></section>;
  const data = people.data;
  if (!data) return null;

  return <section className="people-capacity-panel work-view" aria-labelledby="people-capacity-title">
    <div className="work-view-heading flex flex-wrap items-center justify-between gap-4">
      <div><p className="eyebrow">{t("eyebrow")}</p><h2 className="page-title" id="people-capacity-title">{t("title")}</h2><p className="mt-3 text-slate-600">{t("description")}</p></div>
      {canManage ? <button className="primary-button" type="button" onClick={() => setEditor({ memberId: data.people[0]?.membership_id ?? actorMembershipId })}>{t("action.add")}</button> : null}
    </div>
    {error ? <div className="people-safe-error" role="alert"><p>{error instanceof ApiError && error.code === "RESOURCE_VERSION_MISMATCH" ? t("error.stale") : t("error.mutation")}</p>{error instanceof ApiError && error.code === "RESOURCE_VERSION_MISMATCH" ? <button className="text-button" type="button" onClick={() => void people.refetch()}>{t("action.reload")}</button> : null}</div> : null}
    {data.people.length === 0 ? <p className="people-empty">{t("empty")}</p> : <div className="people-list">{data.people.map((person) => <PersonCard
      canManage={canManage}
      key={person.membership_id}
      person={person}
      skills={data.skills}
      verifierName={(id) => data.people.find((member) => member.membership_id === id)?.display_name ?? t("unknownMember")}
      onEdit={(personSkill) => setEditor({ memberId: person.membership_id, personSkill })}
      onDelete={(personSkill) => void removeSkill(person.membership_id, personSkill)}
    />)}</div>}
    {editor ? <SkillEditor
      actorMembershipId={actorMembershipId}
      members={data.people}
      skills={data.skills}
      state={editor}
      onClose={() => setEditor(null)}
      onSaved={(memberId, saved) => { replacePersonSkill(memberId, saved); setEditor(null); }}
      onStale={() => void people.refetch()}
    /> : null}
  </section>;
}

function PersonCard({ canManage, person, skills, verifierName, onEdit, onDelete }: {
  canManage: boolean;
  person: PersonRecord;
  skills: Skill[];
  verifierName: (membershipId: string) => string;
  onEdit: (personSkill: PersonSkill) => void;
  onDelete: (personSkill: PersonSkill) => void;
}) {
  const t = useTranslations("people");
  const skillName = (skillId: string) => skills.find((skill) => skill.id === skillId)?.name ?? t("unknownSkill");
  return <article className="people-card">
    <header><div><h3>{person.display_name}</h3><p>{t(`role.${person.role}`)}</p></div></header>
    <section aria-label={t("skillsLabel", { name: person.display_name })}>
      <h4>{t("skills")}</h4>
      {person.personSkills.length === 0 ? <p className="people-empty">{t("noSkills")}</p> : <ul className="people-skill-list">{person.personSkills.filter((item) => item.active).map((item) => <li key={item.id}>
        <div><strong>{skillName(item.skill_id)}</strong><span>{t("level", { level: item.level })}</span><span>{t("verifiedBy", { name: verifierName(item.verified_by_membership_id) })}</span></div>
        <ul className="people-evidence-list">{item.evidence.map((evidence) => <li key={evidence.id}>{evidence.summary}</li>)}</ul>
        {canManage ? <div className="people-skill-actions"><button className="text-button" type="button" onClick={() => onEdit(item)}>{t("action.edit")}</button><button className="text-button" type="button" onClick={() => onDelete(item)}>{t("action.delete")}</button></div> : null}
      </li>)}</ul>}
    </section>
    <section aria-label={t("workEvidenceLabel", { name: person.display_name })}>
      <h4>{t("workEvidence")}</h4>
      {person.workEvidence.length === 0 ? <p className="people-empty">{t("noWorkEvidence")}</p> : <ul className="people-evidence-list">{person.workEvidence.map((evidence) => <li key={evidence.id}><strong>{evidence.summary}</strong><span>{evidence.source_resource_type} · v{evidence.source_resource_version}</span></li>)}</ul>}
    </section>
  </article>;
}

function SkillEditor({ actorMembershipId, members, skills, state, onClose, onSaved, onStale }: {
  actorMembershipId: string;
  members: PersonRecord[];
  skills: Skill[];
  state: EditorState;
  onClose: () => void;
  onSaved: (memberId: string, personSkill: PersonSkill) => void;
  onStale: () => void;
}) {
  const t = useTranslations("people");
  const attempt = useMutationAttempt();
  const [memberId, setMemberId] = useState(state.memberId);
  const [skillId, setSkillId] = useState(state.personSkill?.skill_id ?? "");
  const [level, setLevel] = useState(String(state.personSkill?.level ?? 1));
  const [evidence, setEvidence] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!memberId || !skillId) { setFieldError(t("error.required")); return; }
    const numericLevel = Number(level);
    if (!Number.isInteger(numericLevel) || numericLevel < 1 || numericLevel > 5) { setFieldError(t("error.level")); return; }
    const payload = {
      skill_id: skillId,
      level: numericLevel,
      evidence: evidence.trim() ? [{
        evidence_type: "MANAGER_NOTE" as const,
        summary: evidence.trim(),
        source_resource_type: "manager_note",
        source_resource_id: actorMembershipId,
        occurred_at: new Date().toISOString(),
      }] : [],
    };
    setSubmitting(true); setFieldError(null);
    try {
      const result = await setPersonSkill(memberId, skillId, payload, state.personSkill?.version, attempt.keyFor({ memberId, ...payload, version: state.personSkill?.version }));
      attempt.reset(); onSaved(memberId, result.data);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "RESOURCE_VERSION_MISMATCH") {
        await onStale();
        setFieldError(t("error.stale"));
      } else {
        setFieldError(caught instanceof ApiError && caught.fieldErrors.length ? t("error.invalid") : t("error.mutation"));
        if (isDefinitiveMutationRejection(caught)) attempt.reset();
      }
    } finally { setSubmitting(false); }
  }

  return <div className="work-dialog-backdrop" role="presentation"><form aria-label={t("editor.title")} className="work-dialog people-skill-editor" onSubmit={submit}>
    <h2>{state.personSkill ? t("editor.editTitle") : t("editor.addTitle")}</h2>
    <label>{t("editor.member")}<select aria-label={t("editor.member")} className="form-input" value={memberId} onChange={(event) => setMemberId(event.target.value)} disabled={submitting}>{members.map((member) => <option key={member.membership_id} value={member.membership_id}>{member.display_name}</option>)}</select></label>
    <label>{t("editor.skill")}<select aria-label={t("editor.skill")} className="form-input" value={skillId} onChange={(event) => setSkillId(event.target.value)} disabled={submitting}><option value="">{t("editor.selectSkill")}</option>{skills.filter((skill) => skill.active).map((skill) => <option key={skill.id} value={skill.id}>{skill.name}</option>)}</select></label>
    <label>{t("editor.level")}<select aria-label={t("editor.level")} className="form-input" value={level} onChange={(event) => setLevel(event.target.value)} disabled={submitting}>{[1, 2, 3, 4, 5].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    <label>{t("editor.evidence")}<textarea aria-label={t("editor.evidence")} className="form-input" value={evidence} onChange={(event) => setEvidence(event.target.value)} disabled={submitting} /></label>
    <p className="people-editor-hint">{t("editor.evidenceHint")}</p>
    {fieldError ? <p role="alert">{fieldError}</p> : null}
    <div className="work-dialog-actions"><button className="secondary-button" type="button" onClick={onClose} disabled={submitting}>{t("action.cancel")}</button><button className="primary-button" type="submit" disabled={submitting}>{submitting ? t("saving") : t("action.save")}</button></div>
  </form></div>;
}
