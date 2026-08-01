import type { ZodType } from "zod";

import { errorResponseSchema } from "./contracts";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(code);
    this.name = "ApiError";
  }
}

type RequestOptions<T> = {
  init?: RequestInit;
  schema: ZodType<T>;
};

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type");
  if (!contentType?.includes("application/json")) {
    return undefined;
  }
  return response.json();
}

export async function requestJson<T>(
  path: string,
  { init, schema }: RequestOptions<T>,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  const body = await parseBody(response);

  if (!response.ok) {
    const parsedError = errorResponseSchema.safeParse(body);
    if (parsedError.success) {
      throw new ApiError(
        response.status,
        parsedError.data.error.code,
        parsedError.data.error.request_id,
      );
    }
    throw new ApiError(response.status, "UNEXPECTED_RESPONSE");
  }

  const parsedBody = schema.safeParse(body);
  if (!parsedBody.success) {
    throw new ApiError(response.status, "INVALID_RESPONSE");
  }
  return parsedBody.data;
}

export async function requestNoContent(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (response.ok) {
    return;
  }

  const body = await parseBody(response);
  const parsedError = errorResponseSchema.safeParse(body);
  if (parsedError.success) {
    throw new ApiError(
      response.status,
      parsedError.data.error.code,
      parsedError.data.error.request_id,
    );
  }
  throw new ApiError(response.status, "UNEXPECTED_RESPONSE");
}
