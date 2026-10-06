// Organisation members: an owner invites a person with a one-time link, and the
// person who signs up through it joins that organisation as a member. Runs in demo mode.
import { expect, test, type Page } from "@playwright/test";

async function signInAsOwner(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "Continue as demo user" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

/** As the owner, create an invitation and return the link that is shown once. */
async function invite(page: Page, email: string): Promise<string> {
  await page.goto("/profile");
  await page.getByLabel("Their email address").fill(email);
  await page.getByRole("button", { name: "Create invite link" }).click();
  const link = page.getByLabel("Invite link");
  await expect(link).toHaveValue(/\/signup\?invite=[A-Za-z0-9_-]{20,}$/);
  return link.inputValue();
}

test("an owner invites a team member, who joins through the link", async ({ page }) => {
  await signInAsOwner(page);
  await page.goto("/profile");
  await expect(page.getByText("Ollie Reid (you)")).toBeVisible();

  const link = await invite(page, "Riley@Example.test");
  await expect(page.getByText("Invite link for riley@example.test")).toBeVisible();
  await expect(page.getByText("Waiting for them to join")).toBeVisible();
  await signOut(page);

  // the invited person opens the link
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "Join Kearney Formwork Pty Ltd" })).toBeVisible();
  await expect(page.getByLabel("Business name")).toHaveCount(0);
  await expect(page.getByLabel("Email")).toHaveValue("riley@example.test");
  await expect(page.getByLabel("Email")).not.toBeEditable();
  await page.getByLabel("Full name").fill("Riley Nguyen");
  await page.getByLabel("Password").fill("correct-horse-battery");
  await page.getByRole("button", { name: "Join Kearney Formwork Pty Ltd" }).click();

  // they are in the owner's organisation, and see its projects
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Hume St Tower").first()).toBeVisible();
  await page.goto("/profile");
  await expect(page.getByText("Riley Nguyen (you)")).toBeVisible();
  await expect(page.getByText("Ollie Reid", { exact: true })).toBeVisible();
  // as a member, not an owner
  await expect(page.getByText("Only an owner can invite people to the organisation.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create invite link" })).toHaveCount(0);
  await signOut(page);

  // the link works once
  await page.goto(link);
  await expect(page.getByRole("heading", { name: "This invitation can't be used" })).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveCount(0);
});

test("a revoked invitation stops working", async ({ page }) => {
  await signInAsOwner(page);
  const link = await invite(page, "casey@example.test");

  await page.getByRole("button", { name: "Revoke invitation for casey@example.test" }).click();
  await expect(page.getByText("Waiting for them to join")).toHaveCount(0);
  await expect(page.getByLabel("Invite link")).toHaveCount(0);
  await signOut(page);

  await page.goto(link);
  await expect(page.getByRole("heading", { name: "This invitation can't be used" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Create a new organisation instead" })).toBeVisible();
});

test("a made-up invite link is refused, and an ordinary sign-up is unchanged", async ({ page }) => {
  await page.goto("/signup?invite=this-code-was-never-issued-0000");
  await expect(page.getByRole("heading", { name: "This invitation can't be used" })).toBeVisible();

  await page.goto("/signup");
  await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  await expect(page.getByLabel("Business name")).toBeVisible();
  await expect(page.getByLabel("Email")).toBeEditable();
});

test("people who are already members, or already invited, cannot be invited again", async ({ page }) => {
  await signInAsOwner(page);
  await page.goto("/profile");
  const email = page.getByLabel("Their email address");
  const create = page.getByRole("button", { name: "Create invite link" });

  await email.fill("jas@kearneyformwork.test");
  await create.click();
  await expect(page.getByRole("alert").filter({ hasText: "already a member of your organisation" })).toBeVisible();

  await email.fill("casey@example.test");
  await create.click();
  await expect(page.getByLabel("Invite link")).toBeVisible();
  await email.fill("casey@example.test");
  await create.click();
  await expect(page.getByRole("alert").filter({ hasText: "already been invited" })).toBeVisible();
});
