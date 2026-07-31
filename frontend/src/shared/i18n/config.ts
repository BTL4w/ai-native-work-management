export const supportedLocales = ["vi", "en"] as const;

export type AppLocale = (typeof supportedLocales)[number];

export const defaultLocale: AppLocale = "vi";

export function isAppLocale(value: string | undefined): value is AppLocale {
  return supportedLocales.some((locale) => locale === value);
}
