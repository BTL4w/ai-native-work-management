import type { AppLocale } from "./config";
import en from "./messages/en.json";
import vi from "./messages/vi.json";

export const messages = { en, vi } as const;

export function getMessages(locale: AppLocale) {
  return messages[locale];
}
