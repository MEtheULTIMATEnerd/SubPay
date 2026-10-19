import { expect, test } from "@playwright/test";

test("claim support follows confirm, reject and reopen after page reloads", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const review = "/projects/prj-hume/review?item=ci-2";
  const claim = "/projects/prj-hume/claims/clm-7";
  const row = () => page.getByRole("row").filter({ has: page.getByRole("link", { name: /^14\.3 / }) });

  await page.goto(review);
  await page.getByRole("button", { name: "Reopen", exact: true }).click();
  await page.goto(claim);
  await expect(row()).toContainText("No confirmed evidence support");

  await page.goto(review);
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.goto(claim);
  await page.reload();
  await expect(row()).toContainText("Strong support");
  await expect(row()).toContainText("1 human-confirmed");

  await page.goto(review);
  await page.getByRole("button", { name: "Reopen", exact: true }).click();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.goto(claim);
  await page.reload();
  await expect(row()).toContainText("No confirmed evidence support");
  await expect(row()).toContainText("0 human-confirmed");
});
