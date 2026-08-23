"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactElement,
  type ReactNode,
} from "react";

import type { MeResponse } from "@/shared/api/contracts";
import { ApiError, isDefinitiveMutationRejection } from "@/shared/api/client";
import { LocaleSwitcher } from "@/shared/i18n/locale-switcher";
import { ProjectPlanPanel } from "@/features/planning/project-plan";
import { listProjectWeeks } from "@/features/planning/api";
import { AiAssistant } from "@/features/ai-proposals/ai-assistant";

import {
  createProject,
  createTask,
  listMembers,
  listMyTasks,
  listProjects,
  listTasks,
  transitionTask,
  updateProject,
  updateTask,
  type ProjectInput,
  type TaskInput,
} from "./api";
import type { Member, Project, ProjectPage, Task, TaskPage, TaskStatus } from "./contracts";

type View = "aiAssistant" | "projects" | "myTasks";
type ProjectFormState = { project: Project | null };
type TaskFormState = { task: Task | null };
type WorkQueryKey = readonly ["work", string, string];
type MutationAttempt = { fingerprint: string; key: string };
type PlanningContext = { organizationId: string; actorMembershipId: string; canManage: boolean };

const emptyProjectPage: ProjectPage = { items: [], page: 1, page_size: 20, total: 0 };
const emptyTaskPage: TaskPage = { items: [], page: 1, page_size: 20, total: 0 };

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
    reset() {
      attempt.current = null;
    },
  };
}

export function WorkWorkspace({
  actor,
  isLoggingOut = false,
  logoutError = false,
  onLogout,
}: {
  actor: MeResponse;
  isLoggingOut?: boolean;
  logoutError?: boolean;
  onLogout?: () => void | Promise<void>;
}) {
  const t = useTranslations("work");
  const home = useTranslations("home");
  const locale = useLocale();
  const queryClient = useQueryClient();
  const workQueryKey: WorkQueryKey = [
    "work",
    actor.membership.organization_id,
    actor.membership.id,
  ] as const;
  const canManage = actor.membership.role !== "EMPLOYEE";
  const [view, setView] = useState<View>(canManage ? "projects" : "myTasks");
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [projectForm, setProjectForm] = useState<ProjectFormState | null>(null);
  const [taskForm, setTaskForm] = useState<TaskFormState | null>(null);
  const [statusFilter, setStatusFilter] = useState<TaskStatus | "ALL">("ALL");
  const [projectsPage, setProjectsPage] = useState(1);
  const [tasksPage, setTasksPage] = useState(1);
  const [myTasksPage, setMyTasksPage] = useState(1);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [assignmentMode, setAssignmentMode] = useState(false);
  const [projectSection, setProjectSection] = useState<"tasks" | "plan">("tasks");

  const projects = useQuery({
    queryKey: [...workQueryKey, "projects", projectsPage],
    queryFn: () => listProjects(projectsPage),
    enabled: view === "projects",
  });
  const projectTasks = useQuery({
    queryKey: [...workQueryKey, "tasks", selectedProject?.id, tasksPage],
    queryFn: () => listTasks(selectedProject?.id, tasksPage),
    enabled: view === "projects" && selectedProject !== null,
  });
  const myTasks = useQuery({
    queryKey: [...workQueryKey, "myTasks", statusFilter, myTasksPage],
    queryFn: () => listMyTasks(statusFilter === "ALL" ? undefined : statusFilter, myTasksPage),
    enabled: view === "myTasks",
  });

  function openProjects() {
    setAssignmentMode(false);
    setView("projects");
    setSelectedTask(null);
  }

  function openAiAssistant() {
    setAssignmentMode(false);
    setView("aiAssistant");
    setSelectedProject(null);
    setSelectedTask(null);
  }

  function openMyTasks() {
    setAssignmentMode(false);
    setView("myTasks");
    setSelectedProject(null);
    setSelectedTask(null);
  }

  function openAssignmentFlow() {
    setView("projects");
    setSelectedTask(null);
    if (selectedProject) {
      setTaskForm({ task: null });
    } else {
      setAssignmentMode(true);
    }
  }

  function updateCachedTask(updated: Task) {
    const updatePage = (page: TaskPage | undefined) =>
      page
        ? { ...page, items: page.items.map((item) => (item.id === updated.id ? updated : item)) }
        : page;
    queryClient.setQueriesData<TaskPage>({ queryKey: [...workQueryKey, "tasks"] }, updatePage);
    queryClient.setQueriesData<TaskPage>({ queryKey: [...workQueryKey, "myTasks"] }, updatePage);
    void queryClient.invalidateQueries({ queryKey: [...workQueryKey, "myTasks"] });
    setSelectedTask(updated);
  }

  const pageTitle = assignmentMode
    ? t("nav.assignTask")
    : view === "aiAssistant"
    ? t("nav.chat")
    : view === "myTasks"
    ? t("task.myTitle")
    : selectedProject?.name ?? t("project.title");

  return (
    <div className={`workspace-shell ${sidebarCollapsed ? "workspace-shell-collapsed" : ""} ${view === "aiAssistant" ? "workspace-shell-assistant" : ""}`}>
      {view !== "aiAssistant" ? <aside className="workspace-sidebar">
        <div className="sidebar-brand">
          <span aria-hidden="true" className="brand-mark"><AppIcon name="spark" /></span>
          <div className="sidebar-copy min-w-0">
            <p className="brand-name">{t("product")}</p>
            <p className="truncate text-xs text-slate-500">{actor.membership.organization_name}</p>
          </div>
          <button
            aria-label={sidebarCollapsed ? t("sidebar.expand") : t("sidebar.collapse")}
            className="sidebar-collapse-button"
            title={sidebarCollapsed ? t("sidebar.expand") : t("sidebar.collapse")}
            type="button"
            onClick={() => setSidebarCollapsed((value) => !value)}
          >
            <AppIcon name={sidebarCollapsed ? "chevronRight" : "chevronLeft"} />
          </button>
        </div>

        <nav aria-label={t("navigationLabel")} className="sidebar-navigation">
          <p className="sidebar-section-label sidebar-copy">{t("sidebar.workspace")}</p>
          <SidebarItem active={false} icon="chat" label={t("nav.chat")} onClick={openAiAssistant} />
          <SidebarItem active={view === "projects"} icon="grid" label={t("nav.projects")} onClick={openProjects} />
          <SidebarItem active={view === "myTasks"} icon="check" label={t("nav.myTasks")} onClick={openMyTasks} />
          {canManage ? <SidebarItem icon="plus" label={t("nav.assignTask")} onClick={openAssignmentFlow} /> : null}
        </nav>

        <div className="sidebar-account">
          <p className="sidebar-section-label sidebar-copy">{t("sidebar.account")}</p>
          <div className="account-summary">
            <span aria-hidden="true" className="account-avatar">{initials(actor.user.display_name)}</span>
            <div className="sidebar-copy min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900">{actor.user.display_name}</p>
              <p className="truncate text-xs text-slate-500">{actor.user.email}</p>
            </div>
          </div>
          <p className="sidebar-copy account-role">{t(`role.${actor.membership.role}`)} · {locale.toUpperCase()}</p>
          <div className="sidebar-copy sidebar-locale mt-3"><LocaleSwitcher /></div>
          {logoutError ? <p className="sidebar-copy error-message mt-3" role="alert">{home("logoutError")}</p> : null}
          {onLogout ? (
            <button
              aria-label={isLoggingOut ? home("loggingOut") : home("logout")}
              className="sidebar-logout"
              disabled={isLoggingOut}
              title={home("logout")}
              type="button"
              onClick={() => void onLogout()}
            >
              <AppIcon name="logout" />
              <span className="sidebar-copy">{isLoggingOut ? home("loggingOut") : home("logout")}</span>
            </button>
          ) : null}
        </div>
      </aside> : null}

      <div className="workspace-main">
        {view !== "aiAssistant" ? <header className="workspace-topbar">
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-[0.12em] text-slate-400 uppercase">{actor.membership.organization_name}</p>
            <p className="truncate text-base font-semibold text-slate-900">{pageTitle}</p>
          </div>
          <span className="phase-badge"><span aria-hidden="true" className="phase-dot" />{t("sidebar.phase")}</span>
        </header> : null}
        <main className="workspace-content">
        {view === "aiAssistant" ? (
          <AiAssistant
            actor={actor}
            onContinueManually={openProjects}
            onOpenProjects={openProjects}
            onOpenMyTasks={openMyTasks}
            onAssignTask={canManage ? openAssignmentFlow : undefined}
          />
        ) : view === "projects" ? (
          <ProjectsView
            canManage={canManage}
            projects={projects.data ?? emptyProjectPage}
            isLoading={projects.isPending}
            error={projects.error}
            selectedProject={selectedProject}
            tasks={projectTasks.data ?? emptyTaskPage}
            tasksLoading={projectTasks.isPending}
            tasksError={projectTasks.error}
            selectedTask={selectedTask}
            assignmentMode={assignmentMode}
            onSelectProject={(project) => {
              setSelectedProject(project);
              setSelectedTask(null);
              setProjectSection("tasks");
              setTasksPage(1);
              if (project && assignmentMode) {
                setAssignmentMode(false);
                setTaskForm({ task: null });
              }
            }}
            onSelectTask={setSelectedTask}
            onNewProject={() => setProjectForm({ project: null })}
            onEditProject={(project) => setProjectForm({ project })}
            onNewTask={() => setTaskForm({ task: null })}
            onEditTask={(task) => setTaskForm({ task })}
            onRetryProjects={() => void projects.refetch()}
            onRetryTasks={() => void projectTasks.refetch()}
            onProjectsPage={setProjectsPage}
            onTasksPage={setTasksPage}
            onTaskUpdated={updateCachedTask}
            planningContext={{
              organizationId: actor.membership.organization_id,
              actorMembershipId: actor.membership.id,
              canManage,
            }}
            projectSection={projectSection}
            onProjectSection={setProjectSection}
          />
        ) : (
          <MyTasksView
            tasks={myTasks.data ?? emptyTaskPage}
            isLoading={myTasks.isPending}
            error={myTasks.error}
            selectedTask={selectedTask}
            statusFilter={statusFilter}
            onFilter={(filter) => { setStatusFilter(filter); setMyTasksPage(1); }}
            onSelectTask={setSelectedTask}
            onTaskUpdated={(updated) => {
              if (
                statusFilter !== "ALL"
                && updated.status !== statusFilter
                && myTasks.data?.items.length === 1
                && myTasksPage > 1
              ) {
                setMyTasksPage((page) => page - 1);
              }
              updateCachedTask(updated);
            }}
            onRetry={() => void myTasks.refetch()}
            onPage={setMyTasksPage}
            planningContext={{
              organizationId: actor.membership.organization_id,
              actorMembershipId: actor.membership.id,
              canManage,
            }}
          />
        )}
        </main>
      </div>

      {projectForm ? (
        <ProjectForm
          state={projectForm}
          onClose={() => setProjectForm(null)}
          onSaved={(saved) => {
            queryClient.setQueriesData<ProjectPage>({ queryKey: [...workQueryKey, "projects"] }, (page) => page ? { ...page, items: page.items.map((item) => item.id === saved.id ? saved : item) } : page);
            void queryClient.invalidateQueries({ queryKey: [...workQueryKey, "projects"] });
            setSelectedProject(saved);
            setTasksPage(1);
            setProjectForm(null);
          }}
        />
      ) : null}
      {taskForm && selectedProject ? (
        <TaskForm
          state={taskForm}
          projectId={selectedProject.id}
          queryScope={workQueryKey}
          onClose={() => setTaskForm(null)}
          onSaved={(saved) => {
            queryClient.setQueriesData<TaskPage>({ queryKey: [...workQueryKey, "tasks", selectedProject.id] }, (page) => page ? { ...page, items: page.items.map((item) => item.id === saved.id ? saved : item) } : page);
            void queryClient.invalidateQueries({ queryKey: [...workQueryKey, "tasks", selectedProject.id] });
            setSelectedTask(saved);
            setTaskForm(null);
            void queryClient.invalidateQueries({ queryKey: [...workQueryKey, "myTasks"] });
          }}
        />
      ) : null}
    </div>
  );
}

type IconName = "spark" | "chat" | "grid" | "check" | "plus" | "logout" | "chevronLeft" | "chevronRight";

function SidebarItem({ active = false, disabled = false, icon, label, meta, onClick }: {
  active?: boolean; disabled?: boolean; icon: IconName; label: string; meta?: string; onClick?: () => void;
}) {
  return (
    <button
      aria-current={active ? "page" : undefined}
      aria-label={label}
      className={`sidebar-item ${active ? "sidebar-item-active" : ""}`}
      disabled={disabled}
      title={label}
      type="button"
      onClick={onClick}
    >
      <span aria-hidden="true" className="sidebar-item-icon"><AppIcon name={icon} /></span>
      <span className="sidebar-copy sidebar-item-label">{label}</span>
      {meta ? <span className="sidebar-copy sidebar-item-meta">{meta}</span> : null}
    </button>
  );
}

function AppIcon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    spark: <><path d="M12 2.75 13.55 8.45 19.25 10 13.55 11.55 12 17.25l-1.55-5.7L4.75 10l5.7-1.55L12 2.75Z" /><path d="m18.25 15 .65 2.1 2.1.65-2.1.65-.65 2.1-.65-2.1-2.1-.65 2.1-.65.65-2.1Z" /></>,
    chat: <><path d="M7 18.5 3.5 21v-5A8 8 0 1 1 7 18.5Z" /><path d="M8 10h.01M12 10h.01M16 10h.01" /></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
    check: <><path d="M9 11.5 11 13.5 15.5 9" /><rect x="3" y="3" width="18" height="18" rx="5" /></>,
    plus: <><path d="M12 5v14M5 12h14" /><circle cx="12" cy="12" r="9" /></>,
    logout: <><path d="M10 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4M14 8l4 4-4 4M9 12h9" /></>,
    chevronLeft: <path d="m14 7-5 5 5 5" />,
    chevronRight: <path d="m10 7 5 5-5 5" />,
  };
  return <svg aria-hidden="true" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8">{paths[name]}</svg>;
}

function initials(displayName: string) {
  return displayName.split(/\s+/).filter(Boolean).slice(-2).map((part) => part[0]?.toUpperCase()).join("");
}

function ProjectsView(props: {
  canManage: boolean; projects: ProjectPage; isLoading: boolean; error: Error | null;
  selectedProject: Project | null; tasks: TaskPage; tasksLoading: boolean; tasksError: Error | null;
  assignmentMode: boolean;
  selectedTask: Task | null; onSelectProject: (p: Project | null) => void; onSelectTask: (t: Task | null) => void;
  onNewProject: () => void; onEditProject: (p: Project) => void; onNewTask: () => void;
  onEditTask: (task: Task) => void; onTaskUpdated: (task: Task) => void;
  onRetryProjects: () => void; onRetryTasks: () => void;
  onProjectsPage: (page: number) => void; onTasksPage: (page: number) => void;
  planningContext: PlanningContext;
  projectSection: "tasks" | "plan";
  onProjectSection: (section: "tasks" | "plan") => void;
}) {
  const t = useTranslations("work");
  if (props.selectedTask) return <TaskDetail task={props.selectedTask} canEdit={props.canManage} onEdit={() => props.onEditTask(props.selectedTask!)} onUpdated={props.onTaskUpdated} onBack={() => props.onSelectTask(null)} planningContext={props.planningContext} tasks={props.tasks.items} />;
  if (props.selectedProject) {
    return (
      <section>
        <button className="text-button" type="button" onClick={() => props.onSelectProject(null)}>← {t("action.backToProjects")}</button>
        <div className="mt-5 flex flex-wrap items-start justify-between gap-4">
          <div><p className="eyebrow">{t("project.detailEyebrow")}</p><h2 className="page-title">{props.selectedProject.name}</h2><p className="mt-3 text-slate-600">{props.selectedProject.description || t("common.noDescription")}</p></div>
          {props.canManage ? <button className="secondary-button" type="button" onClick={() => props.onEditProject(props.selectedProject!)}>{t("project.edit")}</button> : null}
        </div>
        <div className="mt-8 flex gap-3" role="tablist" aria-label={t("project.sections")}>
          <button aria-selected={props.projectSection === "tasks"} className="secondary-button" role="tab" type="button" onClick={() => props.onProjectSection("tasks")}>{t("project.tasksTab")}</button>
          <button aria-selected={props.projectSection === "plan"} className="secondary-button" role="tab" type="button" onClick={() => props.onProjectSection("plan")}>{t("project.planTab")}</button>
        </div>
        {props.projectSection === "tasks" ? <><div className="mt-10 flex items-center justify-between"><h3 className="text-xl font-semibold">{t("task.sectionTitle")}</h3>{props.canManage ? <button className="primary-button" type="button" onClick={props.onNewTask}>{t("task.create")}</button> : null}</div><TaskCards tasks={props.tasks} isLoading={props.tasksLoading} error={props.tasksError} onRetry={props.onRetryTasks} onSelect={props.onSelectTask} /><Pagination page={props.tasks} onPage={props.onTasksPage} /></> : <ProjectPlanPanel organizationId={props.planningContext.organizationId} actorMembershipId={props.planningContext.actorMembershipId} canManage={props.planningContext.canManage} projectId={props.selectedProject.id} tasks={props.tasks.items} />}
      </section>
    );
  }
  return (
    <section>
      <div className="flex items-center justify-between gap-4"><div><p className="eyebrow">{t("project.eyebrow")}</p><h2 className="page-title">{t("project.title")}</h2></div>{props.canManage ? <button className="primary-button" type="button" onClick={props.onNewProject}>{t("project.create")}</button> : null}</div>
      {props.assignmentMode ? <div className="assignment-hint" role="status"><span aria-hidden="true">↳</span><p>{t("task.selectProjectToAssign")}</p></div> : null}
      {props.isLoading ? <Status text={t("common.loading")} /> : props.error ? <ErrorState error={props.error} onRetry={props.onRetryProjects} /> : props.projects.items.length === 0 ? <EmptyState text={t("project.empty")} /> : <><div className="mt-8 grid gap-4 sm:grid-cols-2">{props.projects.items.map((project) => <button key={project.id} className="resource-card text-left" type="button" onClick={() => props.onSelectProject(project)}><h3 className="font-semibold">{project.name}</h3><p className="mt-2 line-clamp-2 text-sm text-slate-600">{project.description || t("common.noDescription")}</p></button>)}</div><Pagination page={props.projects} onPage={props.onProjectsPage} /></>}
    </section>
  );
}

function MyTasksView(props: { tasks: TaskPage; isLoading: boolean; error: Error | null; selectedTask: Task | null; statusFilter: TaskStatus | "ALL"; onFilter: (status: TaskStatus | "ALL") => void; onSelectTask: (task: Task | null) => void; onTaskUpdated: (task: Task) => void; onRetry: () => void; onPage: (page: number) => void; planningContext: PlanningContext }) {
  const t = useTranslations("work");
  if (props.selectedTask) return <TaskDetail task={props.selectedTask} canEdit={false} onEdit={() => undefined} onUpdated={props.onTaskUpdated} onBack={() => props.onSelectTask(null)} planningContext={props.planningContext} tasks={props.tasks.items} />;
  return <section><div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">{t("task.myEyebrow")}</p><h2 className="page-title">{t("task.myTitle")}</h2></div><label className="text-sm font-medium">{t("task.filterStatus")}<select className="form-input mt-2" value={props.statusFilter} onChange={(event) => props.onFilter(event.target.value as TaskStatus | "ALL")}><option value="ALL">{t("task.allStatuses")}</option><option value="TO_DO">{t("status.TO_DO")}</option><option value="IN_PROGRESS">{t("status.IN_PROGRESS")}</option><option value="DONE">{t("status.DONE")}</option></select></label></div>{props.error ? <ErrorState error={props.error} onRetry={props.onRetry} /> : props.tasks.items.length === 0 && !props.isLoading ? <EmptyState text={t("task.emptyMyTasks")} /> : <><TaskCards tasks={props.tasks} isLoading={props.isLoading} error={null} onRetry={props.onRetry} onSelect={(task) => props.onSelectTask(task)} /><Pagination page={props.tasks} onPage={props.onPage} /></>}</section>;
}

function TaskCards({ tasks, isLoading, error, onRetry, onSelect }: { tasks: TaskPage; isLoading: boolean; error: Error | null; onRetry: () => void; onSelect: (task: Task) => void }) {
  const t = useTranslations("work");
  const locale = useLocale();
  if (isLoading) return <Status text={t("common.loading")} />;
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (tasks.items.length === 0) return <EmptyState text={t("task.empty")} />;
  return <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{tasks.items.map((task) => <button key={task.id} className="resource-card text-left" type="button" onClick={() => onSelect(task)}><span className={`status-pill status-${task.status.toLowerCase()}`}>{t(`status.${task.status}`)}</span><h4 className="mt-4 font-semibold">{task.title}</h4><p className="mt-2 text-sm text-slate-600">{task.assignee?.display_name ?? t("task.unassigned")}</p><p className="mt-1 text-xs text-slate-500">{task.due_date ? formatCalendarDate(task.due_date, locale) : t("task.noDueDate")}</p></button>)}</div>;
}

function ProjectForm({ state, onClose, onSaved }: { state: ProjectFormState; onClose: () => void; onSaved: (project: Project) => void }) {
  const t = useTranslations("work");
  const attempt = useMutationAttempt();
  const [name, setName] = useState(state.project?.name ?? "");
  const [description, setDescription] = useState(state.project?.description ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [issue, setIssue] = useState<FormIssue | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) { setIssue({ message: t("validation.nameRequired"), fields: { name: t("validation.nameRequired") }, conflict: false }); return; }
    setSubmitting(true); setIssue(null);
    try {
      const input: ProjectInput = { name: name.trim(), description: description.trim() || null };
      const key = attempt.keyFor(input);
      const result = state.project ? await updateProject(state.project.id, input, state.project.version, key) : await createProject(input, key);
      onSaved(result.data);
    } catch (caught) {
      setIssue(formIssue(caught, t));
      if (isDefinitiveMutationRejection(caught)) attempt.reset();
    } finally { setSubmitting(false); }
  }
  return <Dialog title={state.project ? t("project.edit") : t("project.create")} onClose={onClose}><form onSubmit={submit}><Field label={t("project.name")} error={issue?.fields.name}><input className="form-input" aria-invalid={Boolean(issue?.fields.name)} value={name} onChange={(e) => setName(e.target.value)} /></Field><Field label={t("project.description")} error={issue?.fields.description}><textarea className="form-input min-h-28" aria-invalid={Boolean(issue?.fields.description)} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>{issue ? <FormIssueNotice issue={issue} /> : null}<FormActions submitting={submitting} onCancel={onClose} saveLabel={t("project.save")} /></form></Dialog>;
}

function TaskForm({ state, projectId, queryScope, onClose, onSaved }: { state: TaskFormState; projectId: string; queryScope: WorkQueryKey; onClose: () => void; onSaved: (task: Task) => void }) {
  const t = useTranslations("work");
  const attempt = useMutationAttempt();
  const [membersPage, setMembersPage] = useState(1);
  const members = useQuery({ queryKey: [...queryScope, "members", membersPage], queryFn: () => listMembers(membersPage) });
  const weeks = useQuery({ queryKey: [...queryScope, "weeks", projectId], queryFn: () => listProjectWeeks(projectId) });
  const [title, setTitle] = useState(state.task?.title ?? "");
  const [description, setDescription] = useState(state.task?.description ?? "");
  const [selectedAssignee, setSelectedAssignee] = useState(state.task?.assignee ?? null);
  const assignee = selectedAssignee?.membership_id ?? "";
  const [dueDate, setDueDate] = useState(state.task?.due_date ?? "");
  const [projectWeekId, setProjectWeekId] = useState(state.task?.project_week_id ?? "");
  const [requiredSkills, setRequiredSkills] = useState(state.task?.required_skill_labels.join("\n") ?? "");
  const [effortHours, setEffortHours] = useState(state.task?.estimated_effort_hours ?? 1);
  const [submitting, setSubmitting] = useState(false);
  const [issue, setIssue] = useState<FormIssue | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !projectWeekId) {
      setIssue({
        message: t("validation.taskRequired"),
        fields: {
          ...(!title.trim() ? { title: t("validation.titleRequired") } : {}),
          ...(!projectWeekId ? { project_week_id: t("validation.weekRequired") } : {}),
        },
        conflict: false,
      });
      return;
    }
    setSubmitting(true); setIssue(null);
    try {
      const input: TaskInput = { project_id: projectId, project_week_id: projectWeekId, title: title.trim(), description: description.trim() || null, assignee_membership_id: assignee || null, required_skill_labels: requiredSkills.split("\n").map((value) => value.trim()).filter(Boolean), estimated_effort_hours: effortHours, due_date: dueDate || null };
      const key = attempt.keyFor(input);
      const result = state.task ? await updateTask(state.task.id, { title: input.title, description: input.description, assignee_membership_id: input.assignee_membership_id, project_week_id: input.project_week_id, required_skill_labels: input.required_skill_labels, estimated_effort_hours: input.estimated_effort_hours, due_date: input.due_date }, state.task.version, key) : await createTask(input, key);
      onSaved(result.data);
    } catch (caught) {
      setIssue(formIssue(caught, t));
      if (isDefinitiveMutationRejection(caught)) attempt.reset();
    } finally { setSubmitting(false); }
  }
  const selectedMemberMissing = selectedAssignee && !members.data?.items.some((member) => member.membership_id === selectedAssignee.membership_id);
  return <Dialog title={state.task ? t("task.edit") : t("task.create")} onClose={onClose}>
    <form onSubmit={submit}>
      <Field label={t("task.title")} error={issue?.fields.title}><input className="form-input" value={title} onChange={(event) => setTitle(event.target.value)} /></Field>
      <Field label={t("task.description")}><textarea className="form-input min-h-24" value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
      <Field label={t("task.week")} error={issue?.fields.project_week_id}><select className="form-input" value={projectWeekId} onChange={(event) => setProjectWeekId(event.target.value)}><option value="">{t("task.selectWeek")}</option>{weeks.data?.filter((week) => week.status !== "COMPLETED").map((week) => <option key={week.id} value={week.id}>{t("task.weekNumber", { number: week.week_number })}</option>)}</select></Field>
      <Field label={t("task.requiredSkills")}><textarea className="form-input" value={requiredSkills} onChange={(event) => setRequiredSkills(event.target.value)} /></Field>
      <Field label={t("task.effortHours")}><input className="form-input" min={1} type="number" value={effortHours} onChange={(event) => setEffortHours(Number(event.target.value))} /></Field>
      <Field label={t("task.assignee")}><select className="form-input" value={assignee} onChange={(event) => setSelectedAssignee(members.data?.items.find((member) => member.membership_id === event.target.value) ?? null)}><option value="">{t("task.unassigned")}</option>{selectedMemberMissing ? <option value={selectedAssignee.membership_id}>{selectedAssignee.display_name}</option> : null}{members.data?.items.map((member: Member) => <option key={member.membership_id} value={member.membership_id}>{member.display_name}</option>)}</select></Field>
      {members.data ? <Pagination page={members.data} onPage={setMembersPage} /> : null}
      <Field label={t("task.dueDate")}><input className="form-input" type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></Field>
      {members.error || weeks.error ? <ErrorState error={(members.error ?? weeks.error) as Error} onRetry={() => { void members.refetch(); void weeks.refetch(); }} /> : null}
      {issue ? <FormIssueNotice issue={issue} /> : null}
      <FormActions submitting={submitting || members.isPending || weeks.isPending} onCancel={onClose} saveLabel={t("task.save")} />
    </form>
  </Dialog>;
}

function TaskDetail({ task, canEdit, onEdit, onUpdated, onBack, planningContext, tasks }: { task: Task; canEdit: boolean; onEdit: () => void; onUpdated: (task: Task) => void; onBack: () => void; planningContext: PlanningContext; tasks: Task[] }) {
  const t = useTranslations("work");
  const locale = useLocale();
  const attempt = useMutationAttempt();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCriteria, setShowCriteria] = useState(false);
  const transitions: Record<TaskStatus, Array<{ target: TaskStatus; label: string }>> = {
    TO_DO: [{ target: "IN_PROGRESS", label: t("task.start") }],
    IN_PROGRESS: [{ target: "TO_DO", label: t("task.returnToDo") }, { target: "DONE", label: t("task.complete") }],
    DONE: [{ target: "IN_PROGRESS", label: t("task.reopen") }],
  };
  async function transition(target: TaskStatus) {
    setSubmitting(true); setError(null);
    try {
      const payload = { taskId: task.id, target, version: task.version };
      onUpdated((await transitionTask(task.id, target, task.version, attempt.keyFor(payload))).data);
    }
    catch (caught) {
      setError(errorMessage(caught, t));
      if (isDefinitiveMutationRejection(caught)) attempt.reset();
    } finally { setSubmitting(false); }
  }
  return <section><button className="text-button" type="button" onClick={onBack}>← {t("action.back")}</button><div className="mt-6 flex flex-wrap items-start justify-between gap-4"><div><span className={`status-pill status-${task.status.toLowerCase()}`}>{t(`status.${task.status}`)}</span><h2 className="page-title mt-4">{task.title}</h2></div>{canEdit ? <button className="secondary-button" type="button" onClick={onEdit}>{t("task.edit")}</button> : null}</div><dl className="mt-8 grid gap-5 rounded-2xl border border-[var(--border)] p-6 sm:grid-cols-2"><Detail label={t("task.assignee")} value={task.assignee?.display_name ?? t("task.unassigned")} /><Detail label={t("task.dueDate")} value={task.due_date ? formatCalendarDate(task.due_date, locale) : t("task.noDueDate")} /><Detail label={t("task.description")} value={task.description || t("common.noDescription")} /></dl><div className="mt-8"><h3 className="font-semibold">{t("task.availableActions")}</h3><div className="mt-3 flex flex-wrap gap-3">{transitions[task.status].map((item) => <button key={item.target} className="primary-button" disabled={submitting} type="button" onClick={() => transition(item.target)}>{item.label}</button>)}</div>{error ? <p className="error-message" role="alert">{error}</p> : null}</div><button className="secondary-button mt-8" type="button" aria-expanded={showCriteria} onClick={() => setShowCriteria((value) => !value)}>{t("task.acceptanceCriteria")}</button>{showCriteria ? <ProjectPlanPanel organizationId={planningContext.organizationId} actorMembershipId={planningContext.actorMembershipId} canManage={planningContext.canManage} projectId={task.project_id} taskId={task.id} tasks={tasks.length ? tasks : [task]} /> : null}</section>;
}

function Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const t = useTranslations("work");
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      ));
      if (focusable.length === 0) return;
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
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [onClose]);
  return <div className="fixed inset-0 z-20 grid place-items-center bg-slate-950/50 p-4" role="presentation"><section ref={dialog} tabIndex={-1} aria-modal="true" role="dialog" aria-labelledby="dialog-title" className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-3xl bg-white p-6 shadow-xl sm:p-8"><div className="flex items-center justify-between"><h2 id="dialog-title" className="text-2xl font-semibold">{title}</h2><button className="text-button" type="button" onClick={onClose} aria-label={t("action.close")}>×</button></div><div className="mt-6">{children}</div></section></div>;
}
function Field({ label, error, children }: { label: string; error?: string; children: ReactElement }) { return <label className="mb-5 block text-sm font-medium">{label}<span className="mt-2 block">{children}</span>{error ? <span className="mt-2 block text-sm text-red-700">{error}</span> : null}</label>; }
function FormActions({ submitting, onCancel, saveLabel }: { submitting: boolean; onCancel: () => void; saveLabel: string }) { const t = useTranslations("work"); return <div className="mt-6 flex justify-end gap-3"><button className="secondary-button" type="button" onClick={onCancel}>{t("action.cancel")}</button><button className="primary-button" disabled={submitting} type="submit">{submitting ? t("common.saving") : saveLabel}</button></div>; }
function Pagination({ page, onPage }: { page: { page: number; page_size: number; total: number }; onPage: (page: number) => void }) {
  const t = useTranslations("work");
  if (page.total <= page.page_size) return null;
  const hasNext = page.page * page.page_size < page.total;
  return <nav aria-label={t("pagination.label")} className="mt-6 flex items-center justify-between gap-3"><button className="secondary-button" disabled={page.page === 1} type="button" onClick={() => onPage(page.page - 1)}>{t("pagination.previous")}</button><span className="text-sm text-slate-600">{t("pagination.page", { page: page.page })}</span><button className="secondary-button" disabled={!hasNext} type="button" onClick={() => onPage(page.page + 1)}>{t("pagination.next")}</button></nav>;
}
function Status({ text }: { text: string }) { return <p className="mt-8 text-sm text-slate-600" role="status">{text}</p>; }
function EmptyState({ text, action }: { text: string; action?: ReactNode }) { return <div className="mt-8 rounded-2xl border border-dashed border-slate-300 p-8 text-center text-slate-600"><p>{text}</p>{action}</div>; }
function ErrorState({ error, onRetry }: { error: Error; onRetry: () => void }) { const t = useTranslations("work"); return <div className="error-message mt-8" role="alert"><p>{errorMessage(error, t)}</p><button className="mt-3 font-semibold underline" type="button" onClick={onRetry}>{t("action.retry")}</button></div>; }
function Detail({ label, value }: { label: string; value: string }) { return <div><dt className="text-xs font-semibold tracking-wide text-slate-500 uppercase">{label}</dt><dd className="mt-2 text-sm">{value}</dd></div>; }
type FormIssue = { message: string; fields: Record<string, string>; conflict: boolean };
type ErrorTranslationKey = "error.conflict" | "error.forbidden" | "error.notFound" | "error.unexpected" | "error.invalidField";
function errorMessage(error: unknown, t: (key: ErrorTranslationKey) => string) { if (error instanceof ApiError) { if (error.code === "RESOURCE_VERSION_MISMATCH") return t("error.conflict"); if (error.code === "FORBIDDEN") return t("error.forbidden"); if (error.code === "RESOURCE_NOT_FOUND") return t("error.notFound"); return `${t("error.unexpected")} (${error.requestId ?? error.code})`; } return t("error.unexpected"); }
function formIssue(error: unknown, t: (key: ErrorTranslationKey) => string): FormIssue {
  const fields = error instanceof ApiError
    ? Object.fromEntries(error.fieldErrors.map((item) => [item.field, `${t("error.invalidField")} (${item.code})`]))
    : {};
  return {
    message: Object.keys(fields).length > 0 ? t("error.invalidField") : errorMessage(error, t),
    fields,
    conflict: error instanceof ApiError && error.code === "RESOURCE_VERSION_MISMATCH",
  };
}
function FormIssueNotice({ issue }: { issue: FormIssue }) {
  const t = useTranslations("work");
  const notice = useRef<HTMLDivElement>(null);
  useEffect(() => notice.current?.focus(), []);
  return <div ref={notice} className="error-message" role="alert" tabIndex={-1}><p>{issue.message}</p>{issue.conflict ? <button className="mt-3 font-semibold underline" type="button" onClick={() => globalThis.location.reload()}>{t("action.reload")}</button> : null}</div>;
}
export function formatCalendarDate(date: string, locale: string) {
  return new Intl.DateTimeFormat(locale, { timeZone: "UTC" }).format(new Date(`${date}T00:00:00.000Z`));
}
