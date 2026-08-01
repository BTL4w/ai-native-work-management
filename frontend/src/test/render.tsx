import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import { AuthProvider } from "@/features/auth/auth-provider";
import type { AppLocale } from "@/shared/i18n/config";
import { AppLocaleProvider } from "@/shared/i18n/locale-provider";

export function renderWithAppProviders(ui: ReactElement, locale: AppLocale = "vi") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  });

  return render(
    <AppLocaleProvider initialLocale={locale}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{ui}</AuthProvider>
      </QueryClientProvider>
    </AppLocaleProvider>,
  );
}

export const managerActor = {
  user: {
    id: "11111111-1111-4111-8111-111111111111",
    email: "manager@example.test",
    display_name: "Demo Manager",
  },
  membership: {
    id: "22222222-2222-4222-8222-222222222222",
    organization_id: "33333333-3333-4333-8333-333333333333",
    organization_name: "Demo Organization",
    role: "MANAGER",
  },
} as const;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function authError(code: string) {
  return {
    error: {
      code,
      message_key: "test.error",
      request_id: "test-request-id",
      field_errors: [],
      details: {},
    },
  };
}
