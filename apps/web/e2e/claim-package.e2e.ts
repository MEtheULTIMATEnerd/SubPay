import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import type { packageJson } from "../lib/claim-package";

async function downloadPackage(page: Page): Promise<ReturnType<typeof packageJson>> {
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download structured JSON" }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe("SubPay_Hume_St_Tower_Claim7.json");
  const file = await download.path();
  expect(file).not.toBeNull();
  return JSON.parse(await readFile(file!, "utf8"));
}

test("review decisions persist into the downloaded draft package", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  const review = "/projects/prj-hume/review?item=ci-2";
  const claim = "/projects/prj-hume/claims/clm-7";
  const exportPage = `${claim}/export`;

  await page.goto(review);
  await page.getByRole("button", { name: "Reopen", exact: true }).click();
  await page.goto(exportPage);
  let pack = await downloadPackage(page);
  expect(pack.items.find((item) => item.contract_item_id === "ci-2")!.evidence).toEqual([]);
  expect(pack.annexure.some((entry) => entry.evidence_id === "ev-11")).toBe(false);

  await page.goto(review);
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.goto(claim);
  await page.getByRole("link", { name: "Evidence package", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${exportPage}$`));
  await page.reload();
  pack = await downloadPackage(page);
  expect(pack.title).toBe("Draft evidence-support package for human review.");
  expect(pack.items.find((item) => item.contract_item_id === "ci-2")!.evidence[0]).toMatchObject({
    evidence_id: "ev-11", approved_support: true, human_status: "confirmed",
  });
  expect(pack.annexure.some((entry) => entry.evidence_id === "ev-11")).toBe(true);
  expect(pack.items.find((item) => item.contract_item_id === "ci-4")!.support_gaps).toContain("remaining 73 m³ quantity support");
  await expect(page.locator("article")).toContainText("remaining 73 m³ quantity support");
  await expect(page.locator("article")).toContainText("does not certify that a contractual requirement has been satisfied");

  await page.goto(review);
  await page.getByRole("button", { name: "Reopen", exact: true }).click();
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await page.goto(exportPage);
  await page.reload();
  pack = await downloadPackage(page);
  expect(pack.items.find((item) => item.contract_item_id === "ci-2")!.evidence).toEqual([]);
  expect(pack.annexure.some((entry) => entry.evidence_id === "ev-11")).toBe(false);
});
