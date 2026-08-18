import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import {
  assistantKeys,
  createConversation,
  getConversation,
  listConversations,
  postAssistantMessage,
} from "./api";

const conversationId = "11111111-1111-4111-8111-111111111111";
const messageId = "22222222-2222-4222-8222-222222222222";
const turnId = "33333333-3333-4333-8333-333333333333";
const orchestrationRunId = "44444444-4444-4444-8444-444444444444";
const conversation = {
  id: conversationId,
  locale: "vi",
  title: null,
  status: "ACTIVE",
  last_message_sequence: 0,
  last_event_sequence: 0,
  created_at: "2026-08-13T10:00:00Z",
  updated_at: "2026-08-13T10:00:00Z",
};
const accepted = {
  conversation_id: conversationId,
  message_id: messageId,
  turn_id: turnId,
  orchestration_run_id: orchestrationRunId,
  status: "QUEUED",
};
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "Content-Type": "application/json" },
});

describe("Assistant API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("scopes query keys by organization and membership", () => {
    expect(assistantKeys.conversations("org-1", "member-1")).toEqual([
      "assistant", "org-1", "member-1", "conversations",
    ]);
    expect(assistantKeys.conversation("org-1", "member-1", conversationId)).toEqual([
      "assistant", "org-1", "member-1", "conversation", conversationId,
    ]);
  });

  it("uses the canonical conversation REST endpoints", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/ai/conversations" && init?.method === "POST") return response(conversation, 201);
      if (path === "/api/v1/ai/conversations") return response({ items: [conversation] });
      if (path === `/api/v1/ai/conversations/${conversationId}`) {
        return response({ conversation, messages: [] });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await createConversation({ locale: "vi", title: null }, "create-key");
    await listConversations();
    await getConversation(conversationId);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/ai/conversations", expect.objectContaining({
      credentials: "include",
      method: "POST",
      headers: expect.objectContaining({ "Idempotency-Key": "create-key" }),
    }));
  });

  it("requires a validated 202 and sends exact version for planning revision", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(accepted, 202));
    vi.stubGlobal("fetch", fetchMock);

    await postAssistantMessage(conversationId, {
      message: "Move the launch to week 3",
      locale: "en",
      card_action: {
        kind: "PLANNING_REVISE",
        workflow_run_id: orchestrationRunId,
        proposal_id: messageId,
      },
    }, "revision-key", 2);

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("Idempotency-Key")).toBe("revision-key");
    expect(headers.get("If-Match")).toBe('"2"');
  });

  it("rejects a valid-looking post response unless status is 202", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(accepted, 200)));

    const error = await postAssistantMessage(conversationId, {
      message: "Plan a launch",
      locale: "en",
    }, "same-attempt-key").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
