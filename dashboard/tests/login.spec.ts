import { expect, test } from "@playwright/test";

// Dashboard sign-in, end to end in a real browser: the session cookie has
// to be set by the sign-in response and then sent by every later fetch and
// EventSource. Runs against tests/fixtures/mock_control_plane.py, whose
// sign-in mode this header switches on (it stays off for other specs).
test.use({ extraHTTPHeaders: { "X-Mock-Auth": "required" } });

const PASSWORD = "correct-password";

test("signed-out visitors get the sign-in page, not data", async ({ page }) => {
  await page.goto("/runs");

  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.locator("table.table")).toHaveCount(0);
});

test("a wrong password is rejected and the form stays", async ({ page }) => {
  await page.goto("/runs");

  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("alert")).toHaveText("Incorrect password.");
  await expect(page.getByLabel("Password")).toHaveValue("");
});

test("signing in shows the app, survives a reload, and signing out ends it", async ({
  page,
}) => {
  await page.goto("/runs");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await expect(page.locator("table.table tbody tr").first()).toBeVisible();

  // The cookie, not in-memory state, is what keeps the session.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();

  // HttpOnly: page scripts must not be able to read the session.
  expect(await page.evaluate(() => document.cookie)).not.toContain("trazo_session");

  await page.getByRole("button", { name: "Sign out" }).first().click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});
