"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";

export default function HomePage() {
  const t = useTranslations("home");
  const common = useTranslations("common");
  const locale = useLocale();
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
      <div className="mx-auto grid min-h-[calc(100vh-3rem)] max-w-6xl overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--surface)] shadow-sm lg:grid-cols-[240px_1fr]">
        <aside className="flex flex-col border-b border-[var(--border)] bg-slate-950 p-6 text-white lg:border-r lg:border-b-0">
          <div>
            <p className="text-xs font-semibold tracking-[0.2em] text-blue-300 uppercase">
              {t("product")}
            </p>
            <h1 className="mt-3 text-xl font-semibold">{actor.membership.organization_name}</h1>
          </div>
          <nav aria-label={t("navigationLabel")} className="mt-8 space-y-2">
            <span className="block rounded-xl bg-white/10 px-4 py-3 text-sm text-slate-300">
              {t("projectsComingSoon")}
            </span>
            <span className="block rounded-xl px-4 py-3 text-sm text-slate-400">
              {t("myTasksComingSoon")}
            </span>
          </nav>
          <div className="mt-8 border-t border-white/10 pt-5 lg:mt-auto">
            <p className="text-sm font-medium">{actor.user.display_name}</p>
            <p className="mt-1 text-xs text-slate-400">{actor.user.email}</p>
            <p className="mt-3 text-xs font-semibold tracking-wide text-blue-300 uppercase">
              {actor.membership.role} · {locale.toUpperCase()}
            </p>
            <button
              className="mt-5 w-full rounded-xl border border-white/20 px-4 py-2.5 text-sm font-medium hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isLoggingOut}
              type="button"
              onClick={handleLogout}
            >
              {isLoggingOut ? t("loggingOut") : t("logout")}
            </button>
            {logoutFailed ? (
              <p className="mt-3 text-sm text-red-300" role="alert">
                {t("logoutError")}
              </p>
            ) : null}
          </div>
        </aside>

        <section aria-labelledby="home-title" className="flex items-center p-8 sm:p-12">
          <div>
            <p className="text-sm font-semibold tracking-wide text-[var(--accent)] uppercase">
              {t("eyebrow")}
            </p>
            <h2 id="home-title" className="mt-4 max-w-3xl text-4xl leading-tight font-semibold">
              {t("title", { name: actor.user.display_name })}
            </h2>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
              {t("description")}
            </p>
            <p
              role="status"
              className="mt-8 inline-flex rounded-full bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-800"
            >
              {t("status", { role: actor.membership.role })}
            </p>
          </div>
        </section>
      </div>
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
