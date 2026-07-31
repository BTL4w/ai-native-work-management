import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { getMessages } from "@/shared/i18n/messages";

import HomePage from "./page";

describe("HomePage", () => {
  it.each(["vi", "en"] as const)("renders the %s locale without missing messages", (locale) => {
    render(
      <NextIntlClientProvider locale={locale} messages={getMessages(locale)}>
        <HomePage />
      </NextIntlClientProvider>,
    );

    expect(screen.getByRole("heading", { level: 1 })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(getMessages(locale).home.status);
  });
});
