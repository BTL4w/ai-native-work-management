import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import {
  decideApproval,
  editProposal,
  getWorkflowRun,
  listPlanningRuns,
  postManagerMessage,
  startPlanningRun,
} from "./api";

const runId = "11111111-1111-4111-8111-111111111111";
const proposalId = "22222222-2222-4222-8222-222222222222";
const approvalId = "33333333-3333-4333-8333-333333333333";
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

const proposalContent = {
  project: { title: "Conference", description: null, start_date: null, due_date: null },
  goal: {
    title: "Engage customers",
    description: null,
    expected_outcomes: ["300 attendees"],
    target_date: null,
  },
  milestones: [],
  project_weeks: [],
  tasks: [],
  dependencies: [],
  assumptions: [{ description: "Budget is not yet confirmed", source: "manager_input" }],
};

const run = {
  id: runId,
  project_id: null,
  status: "WAITING_FOR_DECISION",
  workflow_name: "project_planning",
  workflow_version: "1.0.0",
  verifier_version: "1.0.0",
  input_goal_text: "Plan a conference",
  version: 3,
  created_at: "2026-08-09T10:00:00Z",
  updated_at: "2026-08-09T10:01:00Z",
  current_stage: "await_manager_decision",
  current_proposal: {
    proposal_id: proposalId,
    approval_id: approvalId,
    status: "READY_FOR_DECISION",
    version: 2,
    validation_result: { can_approve: true, errors: [], warnings: [] },
    content: proposalContent,
    change_summary: "Manager edited proposal",
    field_provenance: { default: "MANAGER_EDITED" },
    creator_type: "HUMAN_MANAGER",
    previous_version: {
      version: 1,
      content: { ...proposalContent, project: { ...proposalContent.project, title: "Draft" } },
      field_provenance: { default: "AI_PROPOSED" },
      creator_type: "AI_SYSTEM",
    },
  },
  public_timeline: [],
  allowed_actions: ["EDIT_PROPOSAL", "DECIDE_APPROVAL"],
};

describe("AI proposal API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses typed same-origin planning run endpoints", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/ai/planning-runs" && init?.method === "POST") {
        return response({ run_id: runId, status: "QUEUED", version: 1 }, 202);
      }
      if (path === "/api/v1/workflow-runs?limit=20") return response({ items: [run] });
      if (path === `/api/v1/workflow-runs/${runId}`) return response(run, 200, { ETag: '"3"' });
      if (path.endsWith("/messages")) {
        return response({ run_id: runId, status: "RUNNING", version: 4 }, 202);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await startPlanningRun("Plan a conference", "en", "planning-start-key");
    await listPlanningRuns();
    await expect(getWorkflowRun(runId)).resolves.toMatchObject({ data: run, etag: '"3"' });
    await postManagerMessage(runId, "Budget is known", "planning-message-key");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/ai/planning-runs",
      expect.objectContaining({
        credentials: "include",
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": "planning-start-key" }),
      }),
    );
  });

  it("sends quoted exact versions for edit and decision", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init;
      if (String(input) === `/api/v1/proposals/${proposalId}`) {
        return response({
          proposal_id: proposalId,
          workflow_run_id: runId,
          status: "DRAFT",
          version: 3,
          content: proposalContent,
        }, 202);
      }
      return response({
        approval: { id: approvalId, status: "APPROVED" },
        proposal: { id: proposalId, version: 2, status: "APPROVED" },
        created: {
          project_id: "44444444-4444-4444-8444-444444444444",
          goal_id: null,
          milestone_ids: [],
          task_ids: [],
          dependency_ids: [],
          acceptance_criterion_ids: [],
        },
        workflow_run_id: runId,
        finalization_job_id: "55555555-5555-4555-8555-555555555555",
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await editProposal(proposalId, proposalContent, 2, "proposal-edit-key");
    await decideApproval(approvalId, "APPROVE", 2, "Reviewed", "approval-key");

    for (const call of fetchMock.mock.calls) {
      expect(new Headers(call[1]?.headers).get("If-Match")).toBe('"2"');
      expect(call[1]?.credentials).toBe("include");
    }
  });

  it("rejects malformed successful workflow snapshots", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...run, current_proposal: {
      ...run.current_proposal,
      approval_id: "not-a-uuid",
    } })));

    const error = await getWorkflowRun(runId).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
