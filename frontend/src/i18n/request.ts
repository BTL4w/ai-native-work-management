import { getRequestConfig } from "next-intl/server";

import { defaultLocale, isAppLocale } from "@/shared/i18n/config";
import { getMessages } from "@/shared/i18n/messages";

export default getRequestConfig(async () => {
  const configuredLocale = process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
  const locale = isAppLocale(configuredLocale) ? configuredLocale : defaultLocale;

  return {
    locale,
    messages: getMessages(locale),
    timeZone: "UTC",
  };
});
