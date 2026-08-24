"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { WorkWorkspace } from "@/features/work/workspace";

export default function HomePage() {
  const common = useTranslations("common");
  const router = useRouter();
  const {
    actor,
    bootstrapError,
    isBootstrapping,
    isLoggingOut,
    logout,
    retrySession,
  } = useAuth();
  const [logoutFailed, setLogoutFailed] = useState(false);

  useEffect(() => {
    if (!isBootstrapping && !bootstrapError && actor === null) {
      router.replace("/login");
    }
  }, [actor, bootstrapError, isBootstrapping, router]);

  if (isBootstrapping) {
    return <CenteredStatus message={common("loadingSession")} />;
  }

  if (bootstrapError) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl items-center px-6 py-16">
        <section className="w-full rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-sm">
          <h1 className="text-2xl font-semibold">{common("sessionUnavailableTitle")}</h1>
          <p className="mt-3 text-slate-600">{common("sessionUnavailableDescription")}</p>
          <button className="primary-button mt-6" type="button" onClick={() => retrySession()}>
            {common("retry")}
          </button>
        </section>
      </main>
    );
  }

  if (actor === null) {
    return <CenteredStatus message={common("redirectingToLogin")} />;
  }

  async function handleLogout() {
    setLogoutFailed(false);
    try {
      await logout();
      router.replace("/login");
    } catch {
      setLogoutFailed(true);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--background)]">
      <Suspense fallback={<CenteredStatus message={common("loadingSession")} />}>
        <WorkWorkspace
          key={`${actor.membership.organization_id}:${actor.membership.id}`}
          actor={actor}
          isLoggingOut={isLoggingOut}
          logoutError={logoutFailed}
          onLogout={handleLogout}
        />
      </Suspense>
    </main>
  );
}

function CenteredStatus({ message }: { message: string }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <p className="rounded-full bg-blue-50 px-4 py-2 text-sm font-medium text-blue-800" role="status">
        {message}
      </p>
    </main>
  );
}
