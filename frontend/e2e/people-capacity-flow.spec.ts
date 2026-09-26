import { expect, test, type Page } from "@playwright/test";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Mật khẩu").fill("WorkDemo123!");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page.getByRole("button", { name: "Đăng xuất" })).toBeVisible();
}

test("Manager records skill evidence and availability while Employee stays read only", async ({ page }) => {
  await signIn(page, "manager@example.test");
  await page.getByRole("button", { name: "Con người & kỹ năng" }).click();
  await expect(page.getByRole("heading", { name: "Con người & kỹ năng" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Capacity & workload" })).toBeVisible();

  await page.getByRole("button", { name: "Thêm skill" }).click();
  const skillDialog = page.getByRole("dialog", { name: "Thêm kỹ năng đã xác minh" });
  await skillDialog.getByLabel("Thành viên").selectOption({ label: "Đỗ Ngọc Nam" });
  await skillDialog.getByLabel("Skill").selectOption({ label: "Python" });
  await skillDialog.getByLabel("Mức độ").selectOption("2");
  await skillDialog.getByLabel("Evidence").fill("E2E verified training evidence");
  await skillDialog.getByRole("button", { name: "Lưu skill" }).click();
  await expect(page.getByText("E2E verified training evidence")).toBeVisible();

  await page.getByRole("button", { name: "Thiết lập capacity", exact: true }).click();
  const capacityDialog = page.getByRole("dialog", { name: "Thiết lập capacity" });
  await capacityDialog.getByLabel("Thành viên").selectOption({ label: "Đỗ Ngọc Nam" });
  await capacityDialog.getByLabel("Loại capacity").selectOption("OVERRIDE");
  await capacityDialog.getByLabel("Số giờ", { exact: true }).fill("32");
  await capacityDialog.getByRole("button", { name: "Lưu capacity" }).click();
  await expect(page.getByText("Tuần này · 32 giờ")).toBeVisible();

  await page.getByRole("button", { name: "Thêm lịch nghỉ", exact: true }).click();
  const leaveDialog = page.getByRole("dialog", { name: "Thêm lịch nghỉ" });
  await leaveDialog.getByLabel("Thành viên").selectOption({ label: "Đỗ Ngọc Nam" });
  await leaveDialog.getByLabel("Số giờ nghỉ").fill("8");
  await leaveDialog.getByRole("button", { name: "Lưu lịch nghỉ" }).click();
  await expect(page.getByText("Nghỉ 8 giờ").first()).toBeVisible();
  await page.getByRole("button", { name: "Đăng xuất" }).click();

  await signIn(page, "nam.do@example.test");
  await page.getByRole("button", { name: "Con người & kỹ năng" }).click();
  await expect(page.getByText("E2E verified training evidence")).toBeVisible();
  await expect(page.getByRole("button", { name: "Thêm skill" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Thiết lập capacity", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Thêm lịch nghỉ", exact: true })).toHaveCount(0);
});
