// The evidence journey: add evidence from the library and from the site-capture
// screen, find it again, correct it, and archive it. Runs in demo mode.
import { expect, test, type Page } from "@playwright/test";

// A real 1x1 PNG, so the browser can make a preview of it.
const PHOTO = {
  name: "Level2_conduit_run.png",
  mimeType: "image/png",
  buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64"),
};
const DOCKET = {
  name: "Docket_88213.pdf",
  mimeType: "application/pdf",
  buffer: Buffer.from("%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
};

/** Sign in as the demo user and open the evidence library of a brand-new project. */
async function newProjectEvidencePage(page: Page): Promise<string> {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/projects/new");
  await page.getByLabel("Project name").fill("Riverside Commercial Fitout");
  await page.getByLabel("Head contractor / client").fill("Northbank Builders");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}\/contracts$/);
  const projectUrl = page.url().replace(/\/contracts$/, "");
  await page.goto(`${projectUrl}/evidence`);
  await expect(page.getByText("No evidence yet")).toBeVisible();
  return projectUrl;
}

const picker = (page: Page) => page.locator('input[type="file"]').first();
const dialog = (page: Page) => page.locator("dialog[open]");

/** Upload one file through the library's upload form, with optional details. */
async function upload(page: Page, file: typeof PHOTO, details: { shows?: string; location?: string; tags?: string } = {}) {
  await picker(page).setInputFiles(file);
  if (details.shows) await dialog(page).getByLabel("What does this show?").fill(details.shows);
  if (details.tags) await dialog(page).getByLabel("Tags (optional)").fill(details.tags);
  if (details.location) await dialog(page).getByLabel("Location (optional)").fill(details.location);
  await dialog(page).getByRole("button", { name: "Upload & match" }).click();
  await expect(dialog(page)).toHaveCount(0);
}

test("evidence is uploaded with its details and shows in the library", async ({ page }) => {
  await newProjectEvidencePage(page);

  await picker(page).setInputFiles(PHOTO);
  await expect(dialog(page).getByLabel("Title")).toHaveValue("Level2 conduit run"); // suggested from the filename
  await dialog(page).getByLabel("What does this show?").fill("Conduit installed along the Level 2 east corridor");
  await dialog(page).getByLabel("Location (optional)").fill("Level 2, east corridor");
  await dialog(page).getByLabel("Tags (optional)").fill("Conduit, level 2, conduit");
  await dialog(page).getByRole("button", { name: "Upload & match" }).click();

  const card = page.getByRole("button", { name: /Level2 conduit run/ });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Level 2, east corridor");
  await expect(page.getByText("No evidence yet")).toHaveCount(0);
  // processing finishes by itself and the page updates
  await expect(card.getByText("Ready")).toBeVisible({ timeout: 15_000 });

  await card.click();
  await expect(dialog(page).getByRole("heading", { name: "EV-001 · Level2 conduit run" })).toBeVisible();
  await expect(dialog(page)).toContainText("Conduit installed along the Level 2 east corridor");
  await expect(dialog(page)).toContainText("Level2_conduit_run.png");
  // tags are tidied: lower case, no repeats
  await expect(dialog(page).getByText("conduit", { exact: true })).toHaveCount(1);
  await expect(dialog(page).getByText("level 2", { exact: true })).toBeVisible();
});

test("files that are not supported are refused", async ({ page }) => {
  await newProjectEvidencePage(page);

  await picker(page).setInputFiles({ name: "setup.exe", mimeType: "application/x-msdownload", buffer: Buffer.from("MZ") });
  await dialog(page).getByRole("button", { name: "Upload & match" }).click();

  await expect(dialog(page).getByRole("alert")).toContainText("That file type is not supported");
  await dialog(page).getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("No evidence yet")).toBeVisible();
});

test("the library can be searched and filtered", async ({ page }) => {
  await newProjectEvidencePage(page);
  await upload(page, PHOTO, { shows: "Conduit installed along the corridor" });
  await upload(page, DOCKET, { shows: "Supplier docket for conduit and saddles", tags: "delivery" });

  const photo = page.getByRole("button", { name: /Level2 conduit run/ });
  const docket = page.getByRole("button", { name: /Docket 88213/ });
  await expect(photo).toBeVisible();
  await expect(docket).toBeVisible();

  await page.getByPlaceholder("Search evidence").fill("supplier docket");
  await expect(docket).toBeVisible();
  await expect(photo).toHaveCount(0);

  await page.getByPlaceholder("Search evidence").fill("delivery"); // found by its tag
  await expect(docket).toBeVisible();
  await expect(photo).toHaveCount(0);

  await page.getByPlaceholder("Search evidence").fill("nothing like this");
  await expect(page.getByText("No evidence matches these filters")).toBeVisible();

  await page.getByPlaceholder("Search evidence").fill("");
  await page.getByLabel("Evidence type").selectOption("photo");
  await expect(photo).toBeVisible();
  await expect(docket).toHaveCount(0);

  await page.getByLabel("Evidence type").selectOption("");
  await page.getByLabel("Captured from").fill("2099-01-01");
  await expect(page.getByText("No evidence matches these filters")).toBeVisible();
});

test("evidence details can be corrected, and evidence is archived rather than deleted", async ({ page }) => {
  await newProjectEvidencePage(page);
  await upload(page, PHOTO);

  await page.getByRole("button", { name: /Level2 conduit run/ }).click();
  await dialog(page).getByRole("button", { name: "Edit details" }).click();
  await dialog(page).getByLabel("Title").fill("Conduit run, Level 2 east");
  await dialog(page).getByLabel("Location").fill("Level 2, grid C4");
  await dialog(page).getByLabel("Tags").fill("conduit, inspected");
  await dialog(page).getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog(page).getByRole("heading", { name: "EV-001 · Conduit run, Level 2 east" })).toBeVisible();
  await expect(dialog(page)).toContainText("Level 2, grid C4");
  await expect(dialog(page).getByText("inspected", { exact: true })).toBeVisible();
  await expect(dialog(page)).toContainText("Level2_conduit_run.png"); // the file itself is untouched

  // there is no delete: archive hides it, restore brings it back
  await expect(dialog(page).getByRole("button", { name: /delete/i })).toHaveCount(0);
  await dialog(page).getByRole("button", { name: "Archive", exact: true }).click();
  await expect(dialog(page).getByRole("button", { name: "Restore", exact: true })).toBeVisible();
  await dialog(page).getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("button", { name: /Conduit run, Level 2 east/ })).toHaveCount(0);

  await page.getByLabel("Archived").check();
  await page.getByRole("button", { name: /Conduit run, Level 2 east/ }).click();
  await dialog(page).getByRole("button", { name: "Restore", exact: true }).click();
  await dialog(page).getByRole("button", { name: "Close" }).click();
  await page.getByLabel("Archived").uncheck();
  await expect(page.getByRole("button", { name: /Conduit run, Level 2 east/ })).toBeVisible();
});

test("a photo and a written note can be captured on site", async ({ page }) => {
  const projectUrl = await newProjectEvidencePage(page);
  await page.getByRole("link", { name: "Capture on site" }).click();
  await expect(page).toHaveURL(/\/evidence\/capture$/);
  await expect(page.getByRole("heading", { name: "Which item is this?" })).toBeVisible();

  // nothing to save yet
  const save = page.getByRole("button", { name: "Save, let SubPay suggest" });
  await expect(save).toBeDisabled();

  // a photo, with what it shows and where
  await page.locator('input[type="file"]').setInputFiles(PHOTO);
  await page.getByPlaceholder("What is it? e.g. edge beams").fill("Cable tray above ceiling grid");
  await page.getByPlaceholder("Grid C4, Level 3").fill("Level 2, grid B3");
  await save.click();
  await expect(page.getByText("Saved to the claim")).toBeVisible();

  // then a note with no photo
  await page.getByRole("button", { name: "Take another photo" }).click();
  await page.getByPlaceholder("What is it? e.g. edge beams").fill("Supervisor confirmed rough-in passed inspection");
  await save.click();
  await expect(page.getByText("Saved to the claim")).toBeVisible();

  await page.getByRole("button", { name: "Done" }).click();
  await expect(page).toHaveURL(`${projectUrl}/evidence`);
  await expect(page.getByRole("button", { name: /Site photo/ })).toContainText("Level 2, grid B3");
  await expect(page.getByRole("button", { name: /Site note/ })).toBeVisible();

  // the phone screen never scrolls sideways
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
