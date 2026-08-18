import { describe, expect, it } from "vitest";

import {
  assistantBlockSchema,
  conversationSnapshotSchema,
  type AssistantBlock,
} from "./contracts";

const workflowRunId = "11111111-1111-4111-8111-111111111111";
const proposalId = "22222222-2222-4222-8222-222222222222";

const blocks: AssistantBlock[] = [
  { kind: "text", text: "I found the current project status." },
  { kind: "activity", label_key: "assistant.activity.planning", status: "RUNNING", agent_id: "planning" },
  {
    kind: "work_evidence",
    summary: "Two tasks are blocked.",
    evidence: [{ evidence_id: "task-1", resource_type: "task", resource_id: proposalId, version: 2 }],
  },
  { kind: "question", question: "What is the target date?", response_context: { workflow_run_id: workflowRunId } },
  { kind: "capability_unavailable", capability: "daily_update", message_key: "assistant.unavailable.dailyUpdate" },
  { kind: "planning_run", workflow_run_id: workflowRunId, status: "RUNNING" },
  {
    kind: "proposal",
    workflow_run_id: workflowRunId,
    proposal_id: proposalId,
    proposal_version: 2,
    approval_id: null,
    state: "READY_FOR_DECISION",
    can_approve: true,
    read_only: false,
    current_version: null,
    error_codes: [],
    manual_fallback: null,
  },
  { kind: "decision_result", workflow_run_id: workflowRunId, decision: "APPROVE", proposal_id: proposalId, proposal_version: 2 },
  { kind: "safe_error", code: "MODEL_UNAVAILABLE", message_key: "assistant.error.safe", manual_fallback: "Create the project manually." },
];

describe("Assistant contracts", () => {
  it("strictly parses every public block kind", () => {
    for (const block of blocks) expect(assistantBlockSchema.parse(block)).toEqual(block);
  });

  it("rejects unknown kinds and internal fields", () => {
    expect(() => assistantBlockSchema.parse({ kind: "reasoning", text: "hidden" })).toThrow();
    expect(() => assistantBlockSchema.parse({
      kind: "activity",
      label_key: "assistant.activity.planning",
      status: "RUNNING",
      raw_prompt: "secret",
    })).toThrow();
  });

  it("validates a canonical REST conversation snapshot", () => {
    const parsed = conversationSnapshotSchema.parse({
      conversation: {
        id: workflowRunId,
        locale: "vi",
        title: null,
        status: "ACTIVE",
        last_message_sequence: 1,
        last_event_sequence: 3,
        created_at: "2026-08-13T10:00:00Z",
        updated_at: "2026-08-13T10:01:00Z",
      },
      messages: [{
        id: proposalId,
        sequence: 1,
        role: "ASSISTANT",
        content_blocks: blocks,
        created_at: "2026-08-13T10:01:00Z",
      }],
    });

    expect(parsed.messages[0]?.content_blocks).toHaveLength(9);
  });
});
