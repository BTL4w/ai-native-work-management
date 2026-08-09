import {
  requestJson,
  requestJsonWithMetadata,
  type ApiResult,
} from "@/shared/api/client";

import {
  approvalResultSchema,
  proposalReferenceSchema,
  workflowRunListSchema,
  workflowRunReferenceSchema,
  workflowRunSchema,
  type ApprovalResult,
  type ProposalContent,
  type WorkflowRun,
  type WorkflowRunReference,
} from "./contracts";

const jsonHeaders = { "Content-Type": "application/json" };

function mutate<T>(
  path: string,
  body: unknown,
  key: string,
  schema: Parameters<typeof requestJsonWithMetadata<T>>[1]["schema"],
  version?: number,
): Promise<ApiResult<T>> {
  return requestJsonWithMetadata(path, {
    schema,
    init: {
      method: "POST",
      headers: {
        ...jsonHeaders,
        "Idempotency-Key": key,
        ...(version === undefined ? {} : { "If-Match": `"${version}"` }),
      },
      body: JSON.stringify(body),
    },
  });
}

export function startPlanningRun(
  message: string,
  locale: "vi" | "en",
  key: string,
): Promise<ApiResult<WorkflowRunReference>> {
  return mutate("/api/v1/ai/planning-runs", { message, locale }, key, workflowRunReferenceSchema);
}

export function listPlanningRuns(): Promise<WorkflowRun[]> {
  return requestJson("/api/v1/workflow-runs?limit=20", {
    schema: workflowRunListSchema,
  }).then((result) => result.items);
}

export function getWorkflowRun(runId: string): Promise<ApiResult<WorkflowRun>> {
  return requestJsonWithMetadata(`/api/v1/workflow-runs/${runId}`, {
    schema: workflowRunSchema,
  });
}

export function postManagerMessage(
  runId: string,
  message: string,
  key: string,
): Promise<ApiResult<WorkflowRunReference>> {
  return mutate(
    `/api/v1/workflow-runs/${runId}/messages`,
    { message },
    key,
    workflowRunReferenceSchema,
  );
}

export function editProposal(
  proposalId: string,
  content: ProposalContent,
  version: number,
  key: string,
) {
  return requestJsonWithMetadata(`/api/v1/proposals/${proposalId}`, {
    schema: proposalReferenceSchema,
    init: {
      method: "PATCH",
      headers: { ...jsonHeaders, "Idempotency-Key": key, "If-Match": `"${version}"` },
      body: JSON.stringify({ content }),
    },
  });
}

export function decideApproval(
  approvalId: string,
  decision: "APPROVE" | "REJECT",
  version: number,
  reason: string | null,
  key: string,
): Promise<ApiResult<ApprovalResult>> {
  return mutate(
    `/api/v1/approvals/${approvalId}/decision`,
    { decision, reason },
    key,
    approvalResultSchema,
    version,
  );
}
