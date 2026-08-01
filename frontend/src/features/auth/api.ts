import { z } from "zod";

import { ApiError, requestJson, requestNoContent } from "@/shared/api/client";
import { type MeResponse, meResponseSchema } from "@/shared/api/contracts";

export const loginInputSchema = z.object({
  email: z.email(),
  password: z.string().min(1),
});

export type LoginInput = z.infer<typeof loginInputSchema>;

export type SessionReason = "AUTHENTICATION_REQUIRED" | "SESSION_EXPIRED";

export type SessionSnapshot = {
  actor: MeResponse | null;
  reason: SessionReason | null;
};

export async function login(input: LoginInput): Promise<MeResponse> {
  return requestJson("/api/v1/auth/login", {
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    schema: meResponseSchema,
  });
}

export async function getSession(): Promise<SessionSnapshot> {
  try {
    const actor = await requestJson("/api/v1/me", { schema: meResponseSchema });
    return { actor, reason: null };
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.code === "AUTHENTICATION_REQUIRED" || error.code === "SESSION_EXPIRED")
    ) {
      return { actor: null, reason: error.code };
    }
    throw error;
  }
}

export async function logout(): Promise<void> {
  await requestNoContent("/api/v1/auth/logout", { method: "POST" });
}
