import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";

import { createProject, transitionTask } from "./api";

const project = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "Onboarding",
  description: null,
  version: 1,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T10:00:00Z",
};

const task = {
  id: "22222222-2222-4222-8222-222222222222",
  project_id: project.id,
  title: "Collect documents",
  description: null,
  assignee: {
    membership_id: "33333333-3333-4333-8333-333333333333",
    display_name: "Employee",
  },
  status: "IN_PROGRESS",
  due_date: null,
  version: 2,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-01T11:00:00Z",
};

describe("work API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends a stable caller-owned idempotency key and returns the Project ETag", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(project), {
        status: 201,
        headers: { "Content-Type": "application/json", ETag: '"1"' },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await createProject(
      { name: "Onboarding", description: null },
      "project-submit-key",
    );

    expect(result).toEqual({ data: project, etag: '"1"', replayed: false });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/projects",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": "project-submit-key" }),
      }),
    );
  });

  it("sends If-Match and exposes replay metadata for a Task transition", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(task), {
        headers: {
          "Content-Type": "application/json",
          ETag: '"2"',
          "Idempotency-Replayed": "true",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await transitionTask(task.id, "IN_PROGRESS", 1, "status-submit-key");

    expect(result.replayed).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/tasks/${task.id}/status`,
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Idempotency-Key": "status-submit-key",
          "If-Match": '"1"',
        }),
      }),
    );
  });

  it("preserves structured backend field errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        error: {
          code: "VALIDATION_ERROR",
          message_key: "common.error.validation",
          request_id: "request-123",
          field_errors: [
            { field: "name", code: "string_too_short", message_key: "common.error.invalidField" },
          ],
          details: { source: "request" },
        },
      }), { status: 422, headers: { "Content-Type": "application/json" } }),
    ));

    const error = await createProject({ name: "", description: null }, "project-submit-key")
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      code: "VALIDATION_ERROR",
      messageKey: "common.error.validation",
      fieldErrors: [{ field: "name", code: "string_too_short", messageKey: "common.error.invalidField" }],
      details: { source: "request" },
    });
  });
});
