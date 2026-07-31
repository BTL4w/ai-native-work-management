import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";

import { defaultLocale, isAppLocale } from "@/shared/i18n/config";
import { getMessages } from "@/shared/i18n/messages";

import "./globals.css";

const configuredLocale = process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
const locale = isAppLocale(configuredLocale) ? configuredLocale : defaultLocale;
const localeMessages = getMessages(locale);

export const metadata: Metadata = {
  title: localeMessages.metadata.title,
  description: localeMessages.metadata.description,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider locale={locale} messages={localeMessages}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
