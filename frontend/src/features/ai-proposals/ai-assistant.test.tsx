import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { managerActor, renderWithAppProviders } from "@/test/render";

import { AiAssistant } from "./ai-assistant";

describe("AiAssistant compatibility boundary", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders the conversation-first Assistant instead of the workflow wizard", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), {
      headers: { "Content-Type": "application/json" },
    })));

    renderWithAppProviders(
      <AiAssistant actor={managerActor} connectEvents={() => ({ close: vi.fn() })} />,
    );

    expect(await screen.findByRole("heading", { name: "Trợ lý AI" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Nhắn cho Trợ lý AI" })).toBeVisible();
    expect(screen.queryByText("Hiểu mục tiêu")).not.toBeInTheDocument();
    expect(screen.queryByText("Review và quyết định")).not.toBeInTheDocument();
  });
});
