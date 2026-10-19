import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import type { Db } from "../lib/types";
import type { packageJson } from "../lib/claim-package";

test("complete deterministic SubPay demo walkthrough", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  const remoteCalls: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname.endsWith(".supabase.co") || ["8000", "8001"].includes(url.port)) {
      remoteCalls.push(url.origin);
      await route.abort();
    } else await route.continue();
  });
  const db = (): Promise<Db> => page.evaluate(() => JSON.parse(localStorage.getItem("subpay-db")!));
  const base = "/projects/prj-hume";
  const claim = `${base}/claims/clm-7`;
  const review = `${base}/review?item=ci-3`;
  const claimRow = () => page.getByRole("row").filter({ has: page.getByRole("link", { name: /^14\.4 / }) });
  const coverage = async () => Number((await page.locator("p").filter({ hasText: /^\d+%$/ }).first().innerText()).replace("%", ""));

  await test.step("demo login, dashboard and seeded project", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Continue as demo user" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Ollie");
    expect((await db()).version).toBe(4);
    await page.getByRole("link", { name: /Hume St Tower/ }).first().click();
    await expect(page).toHaveURL(new RegExp(`${base}$`));
    await expect(page.getByRole("heading", { name: "Hume St Tower", exact: true })).toBeVisible();
  });

  await test.step("contract upload, mock extraction and human review", async () => {
    await page.getByRole("link", { name: "Contract", exact: true }).click();
    await expect(page.getByText("Subcontract_HumeSt_Formwork.pdf", { exact: true })).toBeVisible();
    await page.locator('input[type="file"]').setInputFiles({
      name: "Final_demo_subcontract.pdf", mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"),
    });
    const uploaded = page.getByRole("row").filter({ hasText: "Final_demo_subcontract.pdf" });
    await expect(uploaded).toContainText("5 items", { timeout: 15_000 });
    await uploaded.getByRole("link", { name: "Review items" }).click();
    await expect(page.getByText("AI draft", { exact: true })).toHaveCount(5);
    await page.getByRole("button", { name: /2\.1 Formwork, slab edges/ }).click();
    await page.getByRole("button", { name: "Save & confirm" }).click();
    await expect(page.getByText("Confirmed", { exact: true })).toBeVisible();
  });

  let beforeCoverage = 0;
  await test.step("claim baseline has no confirmed soffit evidence", async () => {
    await page.goto(claim);
    await expect(claimRow()).toContainText("No confirmed evidence support");
    await expect(claimRow()).toContainText("$22,800");
    beforeCoverage = await coverage();
  });

  let evidenceId = "";
  await test.step("evidence upload, processing and deterministic suggestions", async () => {
    await page.getByRole("link", { name: "Evidence", exact: true }).click();
    await page.locator('input[type="file"]').first().setInputFiles({
      name: "final_soffit_photo.png", mimeType: "image/png",
      buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64"),
    });
    const dialog = page.locator("dialog[open]");
    await dialog.getByLabel("Title", { exact: true }).fill("Final walkthrough soffit photo");
    await dialog.getByLabel("What does this show?").fill("Formwork slab soffit L3 complete");
    await dialog.getByRole("button", { name: "Upload & match" }).click();
    const card = page.getByRole("button", { name: /Final walkthrough soffit photo/ });
    await expect(card.getByText("Ready", { exact: true })).toBeVisible({ timeout: 15_000 });
    const snapshot = await db();
    evidenceId = snapshot.evidence.find((ev) => ev.title === "Final walkthrough soffit photo")!.id;
    expect(snapshot.evidence_matches.find((m) => m.evidence_id === evidenceId && m.contract_item_id === "ci-3")).toMatchObject({ status: "suggested", source: "ai" });
    await page.goto(claim);
    await expect(claimRow()).toContainText("No confirmed evidence support");
    expect(await coverage()).toBe(beforeCoverage);
  });

  await test.step("confirm, reopen and reject change readiness and survive reload", async () => {
    await page.goto(review);
    const match = () => page.locator("li").filter({ hasText: "Final walkthrough soffit photo" });
    await match().getByRole("button", { name: "Confirm", exact: true }).click();
    await page.goto(claim);
    await page.reload();
    await expect(claimRow()).toContainText("Strong support");
    expect(await coverage()).toBeGreaterThan(beforeCoverage);
    await page.screenshot({ path: testInfo.outputPath("claim-confirmed.png"), fullPage: true });
    await page.goto(review);
    await match().getByRole("button", { name: "Reopen", exact: true }).click();
    await page.goto(claim);
    await page.reload();
    await expect(claimRow()).toContainText("No confirmed evidence support");
    expect(await coverage()).toBe(beforeCoverage);
    await page.goto(review);
    await match().getByRole("button", { name: "Reject", exact: true }).click();
    await page.goto(claim);
    await page.reload();
    await expect(claimRow()).toContainText("No confirmed evidence support");
    expect(await coverage()).toBe(beforeCoverage);
    await expect(page.getByRole("row").filter({ has: page.getByRole("link", { name: /^14\.5 / }) })).toContainText("remaining 73 m³ quantity support");
    await page.goto(review);
    await page.locator("details summary").click();
    await match().getByRole("button", { name: "Reopen", exact: true }).click();
    await match().getByRole("button", { name: "Confirm", exact: true }).click();
  });

  await test.step("a confirmed weak link remains weak and shows its recorded gap", async () => {
    await page.goto(`${base}/review?item=ci-11`);
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await page.goto(claim);
    const weakRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: /^22\.3 / }) });
    await expect(weakRow).toContainText("Weak");
    await expect(weakRow).toContainText("written site instruction");
    await page.reload();
    await expect(weakRow).toContainText("Weak");
  });

  await test.step("download actual JSON and initiate print without claiming a PDF save", async () => {
    await page.goto(claim);
    await page.getByRole("link", { name: "Evidence package", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${claim}/export$`));
    await expect(page.getByText("Draft evidence-support package for human review.", { exact: true }).first()).toBeVisible();
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download structured JSON" }).click();
    const download = await downloading;
    const filename = testInfo.outputPath("final-demo-package.json");
    await download.saveAs(filename);
    const pack: ReturnType<typeof packageJson> = JSON.parse(await readFile(filename, "utf8"));
    const snapshot = await db();
    expect(pack.claim.total_claimed).toBe(snapshot.claim_items.filter((ci) => ci.claim_id === "clm-7").reduce((total, ci) => total + ci.claimed_amount, 0));
    expect(pack.items.find((item) => item.contract_item_id === "ci-3")!.evidence.some((entry) => entry.evidence_id === evidenceId)).toBe(true);
    expect(pack.items.find((item) => item.contract_item_id === "ci-4")!.support_gaps).toContain("remaining 73 m³ quantity support");
    expect(pack.items.find((item) => item.contract_item_id === "ci-11")!.evidence_status).toBe("weak");
    for (const item of pack.items) {
      for (const entry of item.evidence) {
        expect(snapshot.evidence_matches.find((m) => m.evidence_id === entry.evidence_id && m.contract_item_id === item.contract_item_id)!.status).toBe("confirmed");
        expect(snapshot.evidence.find((ev) => ev.id === entry.evidence_id)!.archived).toBe(false);
      }
    }
    expect(pack.disclaimer).toContain("not submitted automatically");
    await page.screenshot({ path: testInfo.outputPath("package.png"), fullPage: true });
    await page.evaluate(() => { window.print = () => {}; });
    await page.getByRole("button", { name: "Export claim pack (PDF)" }).click();
    expect((await db()).audit_events[0].action).toBe("package.print_initiated");
  });

  await test.step("audit, fixtures, persistence and desktop layout", async () => {
    const history = (await db()).audit_events;
    await page.getByRole("link", { name: "Audit trail", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${base}/audit$`));
    await page.reload();
    expect((await db()).audit_events).toEqual(history);
    await expect(page.getByText("Seeded demo example", { exact: true })).toHaveCount(5);
    const decisions = history.filter((ev) => ev.metadata.evidence_id === evidenceId);
    expect(decisions.map((ev) => ev.action)).toEqual(["match.confirmed", "match.reopened", "match.rejected", "match.reopened", "match.confirmed"]);
    expect(decisions.every((ev) => ev.project_id === "prj-hume" && ev.actor_id === "usr-ollie")).toBe(true);
    expect(history.some((ev) => ev.action === "package.download_initiated" && ev.entity_id === "clm-7")).toBe(true);
    await expect(page.getByText("opened package printing (PDF save not verified)", { exact: false })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("audit.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    expect(errors).toEqual([]);
    expect(remoteCalls).toEqual([]);
  });
});
