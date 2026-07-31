"use client";

import { useTranslations } from "next-intl";

export default function HomePage() {
  const t = useTranslations("home");

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl items-center px-6 py-16">
      <section
        aria-labelledby="home-title"
        className="w-full rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-8 shadow-sm sm:p-12"
      >
        <p className="mb-4 text-sm font-semibold tracking-wide text-[var(--accent)] uppercase">
          {t("eyebrow")}
        </p>
        <h1 id="home-title" className="max-w-3xl text-4xl leading-tight font-semibold sm:text-5xl">
          {t("title")}
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">{t("description")}</p>
        <p
          role="status"
          className="mt-10 inline-flex rounded-full bg-blue-50 px-4 py-2 text-sm font-medium text-blue-800"
        >
          {t("status")}
        </p>
      </section>
    </main>
  );
}
