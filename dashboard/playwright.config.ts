import { defineConfig, devices } from "@playwright/test";

// Phase 2 checkpoint (TASKS/PHASE_2.md): "timeline renders (playwright
// smoke)". Runs against the Vite dev server pointed at whatever control
// plane VITE_API_BASE_URL resolves to (default http://localhost:8420,
// matching scripts/smoke/phase2.sh's compose stack) — there must be a
// live control plane with at least one run for tests/timeline.spec.ts to
// find anything to click into. No compose stack handy? Run
// `python tests/fixtures/mock_control_plane.py` in another terminal first
// — a dependency-free stand-in serving one canned run on the same port.
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
