"use client";

import { NextIntlClientProvider } from "next-intl";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { type AppLocale, isAppLocale } from "./config";
import { getMessages } from "./messages";

const localeStorageKey = "work-management-locale";

type LocaleContextValue = {
  locale: AppLocale;
  setLocale: (locale: AppLocale) => void;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function AppLocaleProvider({ initialLocale, children }: { initialLocale: AppLocale; children: ReactNode }) {
  const [locale, setLocaleState] = useState(initialLocale);

  useEffect(() => {
    const storedLocale = globalThis.localStorage?.getItem(localeStorageKey) ?? undefined;
    if (!isAppLocale(storedLocale)) return;
    const timer = globalThis.setTimeout(() => {
      document.documentElement.lang = storedLocale;
      setLocaleState(storedLocale);
    }, 0);
    return () => globalThis.clearTimeout(timer);
  }, []);

  function setLocale(nextLocale: AppLocale) {
    setLocaleState(nextLocale);
    document.documentElement.lang = nextLocale;
    globalThis.localStorage?.setItem(localeStorageKey, nextLocale);
  }

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <NextIntlClientProvider locale={locale} messages={getMessages(locale)} timeZone="UTC">
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}

export function useAppLocale() {
  const context = useContext(LocaleContext);
  if (context === null) throw new Error("useAppLocale must be used inside AppLocaleProvider");
  return context;
}
