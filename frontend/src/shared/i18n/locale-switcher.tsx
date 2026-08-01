"use client";

import { useTranslations } from "next-intl";

import { useAppLocale } from "./locale-provider";

export function LocaleSwitcher({ inverse = false }: { inverse?: boolean }) {
  const t = useTranslations("common");
  const { locale, setLocale } = useAppLocale();
  const baseClass = inverse ? "text-slate-300" : "text-slate-600";
  const activeClass = inverse ? "bg-white/15 text-white" : "bg-blue-50 text-blue-800";

  return (
    <div aria-label={t("languageLabel")} className="flex gap-1" role="group">
      {(["vi", "en"] as const).map((option) => (
        <button
          key={option}
          aria-pressed={locale === option}
          className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold uppercase ${locale === option ? activeClass : baseClass}`}
          type="button"
          onClick={() => setLocale(option)}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
