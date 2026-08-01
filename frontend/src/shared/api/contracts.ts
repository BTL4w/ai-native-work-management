import { z } from "zod";

export const membershipRoleSchema = z.enum(["ADMIN", "MANAGER", "EMPLOYEE"]);

export const meResponseSchema = z.object({
  user: z.object({
    id: z.uuid(),
    email: z.string(),
    display_name: z.string(),
  }),
  membership: z.object({
    id: z.uuid(),
    organization_id: z.uuid(),
    organization_name: z.string(),
    role: membershipRoleSchema,
  }),
});

export type MeResponse = z.infer<typeof meResponseSchema>;

export const errorResponseSchema = z.object({
  error: z.object({
    code: z.string(),
    message_key: z.string(),
    request_id: z.string(),
    field_errors: z.array(
      z.object({
        field: z.string(),
        code: z.string(),
        message_key: z.string(),
      }),
    ),
    details: z.record(z.string(), z.unknown()),
  }),
});
