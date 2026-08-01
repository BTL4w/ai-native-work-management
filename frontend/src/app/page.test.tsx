import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getMessages } from "@/shared/i18n/messages";
import { jsonResponse, managerActor, renderWithAppProviders } from "@/test/render";

import HomePage from "./page";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

describe("HomePage", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each(["vi", "en"] as const)("renders the verified actor in the %s locale", async (locale) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(managerActor)));

    renderWithAppProviders(<HomePage />, locale);

    expect(await screen.findByRole("heading", { name: /Demo Manager/ })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(
      getMessages(locale).home.status.replace("{role}", "MANAGER"),
    );
    expect(screen.getByText("manager@example.test")).toBeVisible();
  });

  it("revokes the session and redirects to login", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(managerActor))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(<HomePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Đăng xuất" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});
