import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a production build in DEMO mode, so they need
// no Supabase project and no API. The empty values below take priority over
// anything in .env.local.
//
//   npx playwright install chromium     (once)
//   npm run test:e2e
const PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.e2e\.ts/,
  forbidOnly: !!process.env.CI,
  reporter: "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    // Set PLAYWRIGHT_CHROMIUM_PATH to use a browser that is already installed.
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: `npm run build && npx next start -p ${PORT}`,
    url: `http://localhost:${PORT}/login`,
    timeout: 240_000,
    reuseExistingServer: false,
    env: {
      NEXT_PUBLIC_SUPABASE_URL: "",
      NEXT_PUBLIC_SUPABASE_ANON_KEY: "",
      NEXT_TELEMETRY_DISABLED: "1",
    },
  },
});
