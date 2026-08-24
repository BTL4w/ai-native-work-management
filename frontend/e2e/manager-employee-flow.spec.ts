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

test("invalid credentials can be corrected without losing the login flow", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("manager@example.test");
  await page.getByLabel("Mật khẩu").fill("incorrect-password");
  await page.getByRole("button", { name: "Đăng nhập" }).click();

  await expect(
    page.getByRole("alert").filter({ hasText: "Email hoặc mật khẩu không đúng." }),
  ).toHaveText("Email hoặc mật khẩu không đúng.");
  await expect(page).toHaveURL(/\/login$/);

  await page.getByLabel("Mật khẩu").fill(password);
  await page.getByRole("button", { name: "Đăng nhập" }).click();

  await expect(page.getByRole("button", { name: "Đăng xuất" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
});

test("Manager plans a week, explicitly assigns a Task, and Employee completes it", async ({ page }) => {
  const suffix = `${Date.now()}`;
  const projectName = `E2E Project ${suffix}`;
  const taskTitle = `E2E Task ${suffix}`;
  const assistantMutations: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/api/v1/ai/")) {
      assistantMutations.push(request.url());
    }
  });

  await signIn(page, "manager@example.test");
  await page.getByRole("button", { name: "Tạo project" }).click();
  await page.getByLabel("Tên project").fill(projectName);
  await page.getByLabel("Mô tả project").fill("Weekly planning browser acceptance flow");
  await page.getByRole("button", { name: "Lưu project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();

  await page.getByRole("tab", { name: "Kế hoạch" }).click();
  await page.getByRole("button", { name: "Thêm mục tiêu" }).click();
  await page.getByLabel("Tiêu đề mục tiêu").fill(`Goal ${suffix}`);
  await page.getByLabel("Kết quả mong đợi").fill("Manual planning remains available");
  await page.getByRole("button", { name: "Lưu mục tiêu" }).click();
  await expect(page.getByText(`Goal ${suffix}`)).toBeVisible();

  await page.getByRole("button", { name: "Thêm milestone" }).click();
  await page.getByLabel("Tên milestone").fill(`Milestone ${suffix}`);
  await page.getByRole("button", { name: "Lưu milestone" }).click();
  await expect(page.getByText(`Milestone ${suffix}`)).toBeVisible();

  await page.getByRole("button", { name: "Thêm tuần" }).click();
  await page.getByLabel("Ngày bắt đầu").fill("2026-08-10");
  await page.getByLabel("Ngày kết thúc").fill("2026-08-16");
  await page.getByLabel("Mục tiêu tuần").fill("Complete the E2E task");
  await page.getByRole("button", { name: "Lưu tuần" }).click();
  await expect(page.getByText("Complete the E2E task")).toBeVisible();
  await page.getByRole("tab", { name: "Tasks" }).click();

  await page.getByRole("button", { name: "Tạo task" }).click();
  await page.getByLabel("Tiêu đề task").fill(taskTitle);
  await page.getByLabel("Tuần dự án").selectOption({ label: "Tuần 1" });
  await page.getByLabel("Người thực hiện").selectOption({ label: "Demo Employee" });
  await page.getByRole("button", { name: "Lưu task" }).click();
  await expect(page.getByRole("heading", { name: taskTitle })).toBeVisible();
  await expect(page.getByText("Demo Employee")).toBeVisible();
  expect(assistantMutations).toEqual([]);
  await signOut(page);

  await signIn(page, "employee@example.test");
  await page.getByRole("button", { name: taskTitle }).click();
  await expect(page.getByRole("button", { name: "Sửa task" })).toHaveCount(0);
  await page.getByRole("button", { name: "Bắt đầu task" }).click();
  await expect(page.getByText("Đang thực hiện")).toBeVisible();
  await page.getByRole("button", { name: "Hoàn thành" }).click();
  await expect(page.getByText("Hoàn thành")).toBeVisible();
  await signOut(page);

  await signIn(page, "manager@example.test");
  await page.getByRole("button", { name: projectName }).click();
  await page.getByRole("button", { name: taskTitle }).click();
  await expect(page.getByText("Hoàn thành")).toBeVisible();
});
