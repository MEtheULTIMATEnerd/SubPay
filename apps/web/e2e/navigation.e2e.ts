// Basic navigation through the app, on desktop and on a phone-sized screen.
// Runs in demo mode: every test starts with a fresh browser and the seeded
// demo data (Ollie Reid, Kearney Formwork Pty Ltd, Hume St Tower).
import { expect, test, type Page } from "@playwright/test";

async function signInAsDemoUser(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function openHumeStTower(page: Page) {
  await signInAsDemoUser(page);
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await page.getByRole("link", { name: /Hume St Tower/ }).first().click();
  await expect(page).toHaveURL(/\/projects\/prj-hume$/);
}

for (const path of ["/dashboard", "/projects", "/projects/new", "/profile", "/projects/prj-hume"]) {
  test(`signed-out visit to ${path} goes to the login page`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(new RegExp(`/login\\?next=${encodeURIComponent(path)}$`));
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
}

test("signing in returns to the page that was asked for", async ({ page }) => {
  await page.goto("/projects");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
});

test("the dashboard shows the user, their organisation and their projects", async ({ page }) => {
  await signInAsDemoUser(page);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ollie");
  await expect(page.getByText("Kearney Formwork Pty Ltd · Owner")).toBeVisible();
  await expect(page.getByRole("link", { name: /Hume St Tower/ }).first()).toBeVisible();
});

test("the main navigation moves between the dashboard and projects", async ({ page }) => {
  await signInAsDemoUser(page);

  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();

  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("each project section opens from the project tabs", async ({ page }) => {
  await openHumeStTower(page);

  const sections: [string, RegExp][] = [
    ["Contract", /\/projects\/prj-hume\/contracts$/],
    ["Evidence", /\/projects\/prj-hume\/evidence$/],
    ["Review", /\/projects\/prj-hume\/review$/],
    ["Claims", /\/projects\/prj-hume\/claims$/],
    ["Audit trail", /\/projects\/prj-hume\/audit$/],
    ["Overview", /\/projects\/prj-hume$/],
  ];
  for (const [tab, url] of sections) {
    await page.getByRole("link", { name: tab, exact: true }).click();
    await expect(page).toHaveURL(url);
    await expect(page.getByRole("heading", { name: "Hume St Tower" })).toBeVisible();
    await expect(page.getByText("Project not found")).toHaveCount(0);
  }
});

test("a project can be created, edited, archived and restored", async ({ page }) => {
  await signInAsDemoUser(page);
  await page.getByRole("link", { name: "New project" }).first().click();
  await expect(page).toHaveURL(/\/projects\/new$/);

  await page.getByLabel("Project name").fill("Riverside Commercial Fitout");
  await page.getByLabel("Head contractor / client").fill("Northbank Builders");
  await page.getByLabel("Site address").fill("12 River Rd, Melbourne VIC");
  await page.getByRole("button", { name: "Create project" }).click();

  // a new project opens on the contract step
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}\/contracts$/);
  await expect(page.getByRole("heading", { name: "Riverside Commercial Fitout" })).toBeVisible();

  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "Edit project" }).click();
  await page.getByLabel("Project name").fill("Riverside Fitout Stage 2");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("heading", { name: "Riverside Fitout Stage 2" })).toBeVisible();

  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.getByRole("button", { name: "Archive project" }).click();
  await expect(page.getByText("This project is archived.")).toBeVisible();

  await page.getByRole("button", { name: "Restore project" }).click();
  await expect(page.getByText("This project is archived.")).toHaveCount(0);

  // and it is listed with the organisation's other projects
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await expect(page.getByRole("link", { name: /Riverside Fitout Stage 2/ })).toBeVisible();
});

test("the project form explains what is wrong", async ({ page }) => {
  await signInAsDemoUser(page);
  await page.goto("/projects/new");
  await page.getByLabel("Project name").fill("Bad Dates");
  await page.getByLabel("Head contractor / client").fill("Builder");
  await page.getByLabel("Start date").fill("2026-06-01");
  await page.getByLabel("End date").fill("2026-05-01");
  await page.getByRole("button", { name: "Create project" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "End date must be after start date" })).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/new$/);
});

test("another organisation's project is reported as not found", async ({ page }) => {
  await signInAsDemoUser(page);
  await page.goto("/projects/prj-secret");
  await expect(page.getByText("Project not found")).toBeVisible();
  await expect(page.getByText("Other Org Secret Job")).toHaveCount(0);
});

test("signing out protects the app again", async ({ page }) => {
  await signInAsDemoUser(page);
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
});

test("a new account starts with its own empty organisation", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Full name").fill("Priya Newstart");
  await page.getByLabel("Business name").fill("Newstart Electrical Pty Ltd");
  await page.getByLabel("Email").fill("priya@newstart.test");
  await page.getByLabel("Password").fill("a-long-enough-password");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Newstart Electrical Pty Ltd · Owner")).toBeVisible();
  await expect(page.getByText("No active projects")).toBeVisible();
  await expect(page.getByText("Hume St Tower")).toHaveCount(0);
});
