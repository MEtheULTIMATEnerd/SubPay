// The contract journey: upload a contract, let extraction run, then review the
// extracted line items. Runs in demo mode with the built-in mock extraction.
import { expect, test, type Page } from "@playwright/test";

const PDF = {
  name: "Riverside_Formwork_Subcontract.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
};

/** Sign in as the demo user and open the contract page of a brand-new project. */
async function newProjectContractPage(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/projects/new");
  await page.getByLabel("Project name").fill("Riverside Commercial Fitout");
  await page.getByLabel("Head contractor / client").fill("Northbank Builders");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}\/contracts$/);
  await expect(page.getByText("No contract uploaded yet")).toBeVisible();
}

test("a contract can be uploaded and is turned into a claim schedule", async ({ page }) => {
  await newProjectContractPage(page);

  await page.locator('input[type="file"]').setInputFiles(PDF);
  await expect(page.getByText(PDF.name)).toBeVisible();
  await expect(page.getByText("No contract uploaded yet")).toHaveCount(0);

  // extraction runs by itself and the page updates when it is done
  await expect(page.getByRole("link", { name: "Review items" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("5 items · 0 confirmed")).toBeVisible();
});

test("files that are not PDF or DOCX are rejected", async ({ page }) => {
  await newProjectContractPage(page);

  await page.locator('input[type="file"]').setInputFiles({
    name: "holiday-photo.png",
    mimeType: "image/png",
    buffer: Buffer.from("not a contract"),
  });

  await expect(page.getByRole("alert").filter({ hasText: "Upload rejected" })).toContainText("PDF or DOCX");
  await expect(page.getByText("No contract uploaded yet")).toBeVisible();
});

test("extracted items are drafts until a person edits, confirms or rejects them", async ({ page }) => {
  await newProjectContractPage(page);
  await page.locator('input[type="file"]').setInputFiles(PDF);
  await page.getByRole("link", { name: "Review items" }).click({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/contracts\/[0-9a-f-]{36}\/items$/);

  // everything the AI extracted starts as a draft
  await expect(page.getByText("AI draft")).toHaveCount(5);
  await expect(page.getByText("5 items need a human check before you claim on them")).toBeVisible();

  // edit a value and confirm
  await page.getByRole("button", { name: /2\.1 Formwork, slab edges/ }).click();
  await page.getByLabel("Quantity").fill("200");
  await page.getByRole("button", { name: "Save & confirm" }).click();
  await expect(page.getByText("Edited · Confirmed")).toHaveCount(1);

  // confirm another without changing it: confirmed, but not marked as edited
  await page.getByRole("button", { name: /2\.2 Formwork, columns/ }).click();
  await page.getByRole("button", { name: "Save & confirm" }).click();
  await expect(page.getByText("Confirmed", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Edited · Confirmed")).toHaveCount(1);

  // reject one
  await page.getByRole("button", { name: /1\.1 Preliminaries/ }).click();
  await page.getByRole("button", { name: "Reject item" }).click();
  await expect(page.getByText("Rejected", { exact: true })).toHaveCount(1);

  // two drafts are left, and the contract list shows the progress
  await expect(page.getByText("AI draft")).toHaveCount(2);
  await page.getByRole("link", { name: "Contracts" }).click();
  await expect(page.getByText("5 items · 2 confirmed")).toBeVisible();
});
