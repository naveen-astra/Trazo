import { expect, test } from "@playwright/test";

// Phase 2 checkpoint (TASKS/PHASE_2.md): "timeline renders". Exercises the
// exact user flow TRZ-P2-07 built: land on the runs list, open a run,
// confirm the kind-colored/step-grouped timeline renders, open the
// payload drawer for one event. Assumes a live control plane with at
// least one finished run — scripts/smoke/phase2.sh seeds exactly one
// ("phase2-smoke", the toy LangGraph agent) before running this spec.
//
// The runs list moved to /runs when the Overview became the index route,
// and run detail now opens on the Flow view with the timeline behind a
// tab — so the walk to the timeline is two clicks, not one.
test("runs list -> run detail -> timeline -> payload drawer", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();

  const firstRun = page.locator("table.table tbody tr").first();
  await expect(firstRun).toBeVisible();
  await expect(firstRun.locator(".badge")).toContainText("ok");

  await firstRun.locator("a.table__mono").click();
  await expect(page).toHaveURL(/\/runs\//);

  await page.getByRole("tab", { name: "Timeline" }).click();

  const timeline = page.locator(".timeline");
  await expect(timeline).toBeVisible();

  const stepHeaders = page.locator(".timeline__step-name");
  await expect(stepHeaders).toHaveCount(2);
  await expect(stepHeaders.nth(0)).toContainText("plan");
  await expect(stepHeaders.nth(1)).toContainText("search");

  await expect(page.locator(".timeline__kind", { hasText: "llm.call" })).toBeVisible();
  await expect(page.locator(".timeline__kind", { hasText: "tool.call" })).toBeVisible();

  await page.locator(".timeline__kind", { hasText: "tool.call" }).click();
  const drawer = page.getByRole("dialog", { name: "payload for tool.call" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "tool.call" })).toBeVisible();

  await drawer.getByRole("button", { name: "close" }).click();
  await expect(drawer).toBeHidden();
});
