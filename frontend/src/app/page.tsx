"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { WorkWorkspace } from "@/features/work/workspace";

export default function HomePage() {
  const t = useTranslations("home");
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
    <main className="min-h-screen bg-[var(--background)] p-4 sm:p-6">
      <div className="mx-auto mb-3 flex max-w-6xl items-center justify-end gap-4">
        {logoutFailed ? <p className="text-sm text-red-700" role="alert">{t("logoutError")}</p> : null}
        <button className="secondary-button" disabled={isLoggingOut} type="button" onClick={handleLogout}>
          {isLoggingOut ? t("loggingOut") : t("logout")}
        </button>
      </div>
      <div className="mx-auto max-w-6xl"><WorkWorkspace key={`${actor.membership.organization_id}:${actor.membership.id}`} actor={actor} /></div>
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
