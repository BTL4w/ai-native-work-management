import { expect, test, type Page } from "@playwright/test";

const password = "WorkDemo123!";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Mật khẩu").fill(password);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("button", { name: "Đăng xuất" })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Đăng xuất" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

async function openNewConversation(page: Page) {
  await page
    .getByRole("navigation", { name: "Điều hướng chính" })
    .getByRole("button", { name: "Cuộc trò chuyện mới" })
    .click();
  await expect(page.getByRole("heading", { name: "Trợ lý AI" })).toBeVisible();
}

async function send(page: Page, message: string) {
  const composer = page.getByLabel("Nhắn cho Trợ lý AI");
  await composer.fill(message);
  await page.getByRole("button", { name: "Gửi" }).click();
  await expect
    .poll(
      async () => {
        const conversationId = new URL(page.url()).searchParams.get("conversation");
        if (!conversationId) return false;
        const response = await page.request.get(`/api/v1/ai/conversations/${conversationId}`);
        if (!response.ok()) return false;
        const snapshot = (await response.json()) as {
          conversation?: { last_event_sequence?: number };
          messages?: Array<{ content_blocks?: Array<{ kind?: string }> }>;
        };
        return Boolean(
          snapshot.conversation?.last_event_sequence &&
            snapshot.messages?.some((item) =>
              item.content_blocks?.some((block) => block.kind === "activity"),
            ),
        );
      },
      { message: "persisted assistant activity event", timeout: 20_000 },
    )
    .toBe(true);
  await expect(page.locator(".assistant-activity").first()).toBeVisible();
}

test("Assistant enforces Employee scope and completes one approval-gated Manager plan", async ({
  page,
}) => {
  await signIn(page, "employee@example.test");
  await openNewConversation(page);
  await send(page, "Công việc hiện tại và task tiếp theo của tôi là gì?");
  await expect(page.getByRole("heading", { name: "Bằng chứng công việc" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Phê duyệt kế hoạch" })).toHaveCount(0);

  await openNewConversation(page);
  await send(page, "Hãy lập một project plan và tự phê duyệt cho tôi");
  await expect(page.getByRole("heading", { name: "Khả năng chưa khả dụng" })).toBeVisible();
  await expect(page.locator(".assistant-planning-card")).toHaveCount(0);
  await signOut(page);

  await signIn(page, "manager@example.test");
  await openNewConversation(page);
  await send(page, "Lập kế hoạch ra mắt sản phẩm trong quý tới");

  await expect(page.locator(".assistant-question, .assistant-planning-card").first()).toBeVisible();
  const question = page.getByRole("heading", { name: "Cần thêm thông tin" });
  if (await question.isVisible()) {
    await send(page, "Ngân sách đã được duyệt và phạm vi là một thị trường.");
  }

  await expect(page.getByText("Proposal v1", { exact: true })).toBeVisible();
  await expect(page.getByText("Chờ bạn phê duyệt")).toBeVisible();

  await page.getByRole("button", { name: "Nhờ AI chỉnh" }).click();
  await page.getByLabel("Yêu cầu AI chỉnh proposal").fill(
    "Dời mốc cuối một tuần và bổ sung công việc xác nhận nhà cung cấp.",
  );
  await page.getByRole("button", { name: "Gửi yêu cầu chỉnh" }).click();

  await expect(page.getByText("Proposal v2", { exact: true })).toBeVisible();
  await expect(page.getByText("Version chỉ đọc").first()).toBeVisible();
  await page.getByRole("button", { name: "Phê duyệt kế hoạch" }).click();
  await expect(page.getByRole("heading", { name: "Kết quả quyết định" })).toBeVisible();

  await page.getByRole("button", { name: "Projects" }).click();
  await expect(page.getByRole("button", { name: "Proposed project" })).toHaveCount(1);

  await page.locator(".assistant-conversation-items button").first().click();
  await page.reload();
  await expect(page.getByText("Proposal v2", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Kết quả quyết định" })).toHaveCount(1);
});
