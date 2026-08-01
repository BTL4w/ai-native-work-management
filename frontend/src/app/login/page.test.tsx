import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  authError,
  jsonResponse,
  managerActor,
  renderWithAppProviders,
} from "@/test/render";

import LoginPage from "./page";

const navigation = vi.hoisted(() => ({ replace: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
}));

describe("LoginPage", () => {
  beforeEach(() => {
    navigation.replace.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders an anonymous session and validates fields before login", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(authError("AUTHENTICATION_REQUIRED"), 401));
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(<LoginPage />);
    const email = await screen.findByLabelText("Email");
    fireEvent.change(email, { target: { value: "invalid" } });
    fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByText("Nhập một địa chỉ email hợp lệ.")).toBeVisible();
    expect(screen.getByText("Mật khẩu không được để trống.")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows the generic invalid-credentials message", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(authError("AUTHENTICATION_REQUIRED"), 401))
      .mockResolvedValueOnce(jsonResponse(authError("INVALID_CREDENTIALS"), 401));
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(<LoginPage />);
    fireEvent.change(await screen.findByLabelText("Mật khẩu"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Email hoặc mật khẩu không đúng.",
    );
  });

  it("logs in through the same-origin API and redirects home", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(authError("AUTHENTICATION_REQUIRED"), 401))
      .mockResolvedValueOnce(jsonResponse(managerActor));
    vi.stubGlobal("fetch", fetchMock);

    renderWithAppProviders(<LoginPage />);
    fireEvent.change(await screen.findByLabelText("Mật khẩu"), {
      target: { value: "WorkDemo123!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v1/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          email: "manager@example.test",
          password: "WorkDemo123!",
        }),
      }),
    );
  });

  it("explains when the previous session expired", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(authError("SESSION_EXPIRED"), 401)),
    );

    renderWithAppProviders(<LoginPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
    );
  });
});
