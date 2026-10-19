import { beforeEach, afterEach, expect, test, vi } from "vitest";

vi.mock("./env", () => ({ LIVE: false }));

import { completeness, readiness, reviewMatch, createClaim } from "./api";
import { commit, getDb, resetDb } from "./store";
import type { MatchStatus } from "./types";

beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
  });
  resetDb({ profile_id: "usr-ollie" });
  commit((d) => {
    d.evidence_matches = d.evidence_matches.filter((m) => m.id === "em-1");
    d.evidence_matches[0].status = "suggested";
    d.claim_items = d.claim_items.filter((item) => item.contract_item_id === "ci-1");
  });
});

afterEach(() => vi.unstubAllGlobals());

test.each<MatchStatus>(["suggested", "rejected"])("%s links provide no confirmed support", (status) => {
  reviewMatch("em-1", status);
  const result = readiness(getDb(), "clm-7");
  expect(result.coverage).toBe(0);
  expect(result.rows[0]).toMatchObject({ state: "missing", confirmedCount: 0 });
  expect(result.rows[0].supportGaps).toContain("No confirmed evidence support");
});

test("confirm and reopen update calculated support immediately", () => {
  reviewMatch("em-1", "confirmed");
  expect(readiness(getDb(), "clm-7").rows[0]).toMatchObject({ state: "strong", confirmedCount: 1 });
  expect(readiness(getDb(), "clm-7").coverage).toBe(100);
  reviewMatch("em-1", "suggested");
  expect(readiness(getDb(), "clm-7").rows[0].state).toBe("missing");
  expect(readiness(getDb(), "clm-7").coverage).toBe(0);
});

test("weak confirmed evidence remains weak and recorded gaps prevent strong support", () => {
  reviewMatch("em-1", "confirmed");
  commit((d) => { d.evidence_matches[0].assessment = "weak"; });
  expect(readiness(getDb(), "clm-7").rows[0].state).toBe("weak");
  commit((d) => {
    d.evidence_matches[0].assessment = "strong";
    d.evidence_matches[0].missing_evidence = ["quantity confirmation"];
  });
  expect(readiness(getDb(), "clm-7").rows[0]).toMatchObject({
    state: "partial", supportGaps: ["quantity confirmation"],
  });
  expect(readiness(getDb(), "clm-7").coverage).toBe(0);
});

test("archived evidence and unconfirmed contract lines cannot supply strong support", () => {
  reviewMatch("em-1", "confirmed");
  commit((d) => { d.evidence.find((e) => e.id === "ev-1")!.archived = true; });
  expect(readiness(getDb(), "clm-7").rows[0].state).toBe("missing");
  commit((d) => {
    d.evidence.find((e) => e.id === "ev-1")!.archived = false;
    d.contract_items.find((item) => item.id === "ci-1")!.review_status = "draft";
  });
  expect(readiness(getDb(), "clm-7").rows[0].state).toBe("partial");
  expect(readiness(getDb(), "clm-7").rows[0].supportGaps).toContain("Contract line requires human confirmation");
});

test("coverage is the claimed-value share with strong confirmed support", () => {
  reviewMatch("em-1", "confirmed");
  commit((d) => {
    d.claim_items[0].claimed_amount = 100;
    d.claim_items.push({ ...d.claim_items[0], id: "other", contract_item_id: "ci-2", claimed_amount: 300 });
  });
  expect(readiness(getDb(), "clm-7").coverage).toBe(25);
  expect(readiness(getDb(), "clm-7").counts.missing).toBe(1);
  commit((d) => { d.claim_items.forEach((item) => { item.claimed_amount = 0; }); });
  expect(readiness(getDb(), "clm-7").coverage).toBe(0);
});

test.each<MatchStatus>(["confirmed", "rejected", "suggested"])("%s decisions survive a fresh store load", async (status) => {
  reviewMatch("em-1", "confirmed");
  reviewMatch("em-1", status);
  vi.resetModules();
  const reloaded = await import("./store");
  const db = reloaded.getDb();
  expect(db.evidence_matches[0].status).toBe(status);
  expect(readiness(db, "clm-7").rows[0].state).toBe(status === "confirmed" ? "strong" : "missing");
});

test("claims still include confirmed contract items and start without invented evidence", () => {
  const id = createClaim("prj-hume");
  const result = readiness(getDb(), id);
  expect(result.rows.length).toBeGreaterThan(0);
  expect(result.rows.every((row) => row.item.review_status === "confirmed")).toBe(true);
  expect(result.rows.every((row) => row.state === "missing")).toBe(true);
  expect(completeness([])).toBe("missing");
});
