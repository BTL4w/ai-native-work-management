import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "cd ../backend && APP_DATABASE_URL=postgresql+psycopg://work_management:work_management@localhost:5432/work_management_e2e uv run fastapi run app/main.py --host 127.0.0.1 --port 8100",
      url: "http://127.0.0.1:8100/openapi.json",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "API_ORIGIN=http://127.0.0.1:8100 NEXT_DIST_DIR=.next-e2e corepack pnpm@10 start --hostname 127.0.0.1 --port 3100",
      url: "http://127.0.0.1:3100/login",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
