import { z } from "zod";

const uuid = z.uuid();
const strict = <T extends z.ZodRawShape>(shape: T) => z.object(shape).strict();

export const textBlockSchema = strict({ kind: z.literal("text"), text: z.string() });
export const activityBlockSchema = strict({
  kind: z.literal("activity"),
  label_key: z.string(),
  status: z.enum(["PENDING", "RUNNING", "COMPLETED", "FAILED"]),
  agent_id: z.string().nullable().optional(),
});
const publicEvidenceSchema = strict({
  evidence_id: z.string(),
  resource_type: z.string(),
  resource_id: uuid,
  version: z.number().int().positive().nullable().optional(),
});
export const workEvidenceBlockSchema = strict({
  kind: z.literal("work_evidence"),
  summary: z.string(),
  evidence: z.array(publicEvidenceSchema),
});
export const questionBlockSchema = strict({
  kind: z.literal("question"),
  question: z.string(),
  response_context: z.record(z.string(), z.unknown()),
});
export const capabilityUnavailableBlockSchema = strict({
  kind: z.literal("capability_unavailable"),
  capability: z.string(),
  message_key: z.string(),
});
export const planningRunBlockSchema = strict({
  kind: z.literal("planning_run"),
  workflow_run_id: uuid,
  status: z.string(),
});
export const proposalBlockSchema = strict({
  kind: z.literal("proposal"),
  workflow_run_id: uuid,
  proposal_id: uuid,
  proposal_version: z.number().int().positive(),
  approval_id: uuid.nullable().optional(),
  state: z.string().nullable().optional(),
  can_approve: z.boolean().nullable().optional(),
  read_only: z.boolean().default(false),
  current_version: z.number().int().positive().nullable().optional(),
  error_codes: z.array(z.string()).default([]),
  manual_fallback: z.string().nullable().optional(),
});
export const decisionResultBlockSchema = strict({
  kind: z.literal("decision_result"),
  workflow_run_id: uuid,
  decision: z.enum(["APPROVE", "REJECT", "UNKNOWN"]),
  proposal_id: uuid,
  proposal_version: z.number().int().positive(),
});
export const safeErrorBlockSchema = strict({
  kind: z.literal("safe_error"),
  code: z.string(),
  message_key: z.string(),
  manual_fallback: z.string().nullable().optional(),
});

export const assistantBlockSchema = z.discriminatedUnion("kind", [
  textBlockSchema,
  activityBlockSchema,
  workEvidenceBlockSchema,
  questionBlockSchema,
  capabilityUnavailableBlockSchema,
  planningRunBlockSchema,
  proposalBlockSchema,
  decisionResultBlockSchema,
  safeErrorBlockSchema,
]);

export const conversationSchema = strict({
  id: uuid,
  locale: z.enum(["vi", "en"]),
  title: z.string().nullable(),
  status: z.string(),
  last_message_sequence: z.number().int().nonnegative(),
  last_event_sequence: z.number().int().nonnegative(),
  created_at: z.iso.datetime(),
  updated_at: z.iso.datetime(),
});
export const assistantMessageSchema = strict({
  id: uuid,
  sequence: z.number().int().positive(),
  role: z.enum(["USER", "ASSISTANT", "SYSTEM"]),
  content_blocks: z.array(assistantBlockSchema),
  created_at: z.iso.datetime(),
});
export const conversationListSchema = strict({ items: z.array(conversationSchema) });
export const conversationSnapshotSchema = strict({
  conversation: conversationSchema,
  messages: z.array(assistantMessageSchema),
});
export const assistantTurnAcceptedSchema = strict({
  conversation_id: uuid,
  message_id: uuid,
  turn_id: uuid,
  orchestration_run_id: uuid,
  status: z.literal("QUEUED"),
});

export type AssistantBlock = z.infer<typeof assistantBlockSchema>;
export type AssistantConversation = z.infer<typeof conversationSchema>;
export type AssistantMessage = z.infer<typeof assistantMessageSchema>;
export type ConversationSnapshot = z.infer<typeof conversationSnapshotSchema>;
export type AssistantTurnAccepted = z.infer<typeof assistantTurnAcceptedSchema>;
export type PostMessageInput = {
  message: string;
  locale: "vi" | "en";
  card_action?: {
    kind: "PLANNING_INPUT" | "PLANNING_REVISE";
    workflow_run_id: string;
    proposal_id?: string;
  };
};
