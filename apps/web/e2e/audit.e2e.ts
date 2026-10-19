import { expect, test, type Page } from "@playwright/test";
import type { AuditEvent } from "../lib/types";

const events = (page: Page): Promise<AuditEvent[]> => page.evaluate(() => JSON.parse(localStorage.getItem("subpay-db")!).audit_events);

test("review and export actions create accurate persisted demo audit events", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const history = await events(page);
  const exportPath = "/projects/prj-hume/claims/clm-7/export";
  const auditPath = "/projects/prj-hume/audit";
  await page.goto(auditPath);
  await expect(page.getByText("Seeded demo example", { exact: true })).toHaveCount(5);
  await page.goto(exportPath);
  await page.reload();
  expect(await events(page)).toEqual(history);

  await page.goto("/projects/prj-hume/review?item=ci-2");
  await page.getByRole("button", { name: "Reopen", exact: true }).click();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.locator("details summary").click();
  await page.getByRole("button", { name: "Reopen", exact: true }).click();
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.goto(exportPath);

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download structured JSON" }).click();
  expect((await download).suggestedFilename()).toMatch(/Claim7\.json$/);
  expect((await events(page))[0]).toMatchObject({ action: "package.download_initiated", metadata: { format: "json" } });

  // A throwing browser print API must not record a successful action.
  const beforeFailure = await events(page);
  await page.evaluate(() => { window.print = () => { throw new Error("Print unavailable in this test"); }; });
  await page.getByRole("button", { name: "Export claim pack (PDF)" }).click();
  await expect(page.getByText("Print unavailable in this test", { exact: true })).toBeVisible();
  expect(await events(page)).toEqual(beforeFailure);

  await page.evaluate(() => { window.print = () => {}; });
  await page.getByRole("button", { name: "Export claim pack (PDF)" }).click();
  const saved = await events(page);
  expect(saved[0]).toMatchObject({ action: "package.print_initiated", metadata: { format: "pdf", outcome: "print_initiated" } });
  expect(saved.slice(-history.length)).toEqual(history);
  expect(saved.filter((event) => event.entity_id === "em-9").map((event) => event.action)).toEqual([
    "match.confirmed", "match.reopened", "match.rejected", "match.reopened",
  ]);

  await page.goto(auditPath);
  await page.reload();
  expect(await events(page)).toEqual(saved);
  await expect(page.getByText("opened package printing (PDF save not verified)", { exact: false })).toBeVisible();
  await expect(page.getByText("initiated a JSON package download", { exact: false })).toBeVisible();
  await expect(page.locator("li").filter({ hasText: "confirmed a match" }).filter({ hasText: "em-9" })).toContainText("Ollie Reid");
  await expect(page.locator("time").first()).toHaveAttribute("datetime", /\d{4}-\d{2}-\d{2}T/);
});
