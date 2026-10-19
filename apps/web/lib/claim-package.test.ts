import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("./env", () => ({ LIVE: false }));

import { readiness, reviewMatch } from "./api";
import { annexure, packageJson, PACKAGE_TITLE } from "./claim-package";
import { getDb, resetDb, commit } from "./store";
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
    d.claim_items = d.claim_items.filter((ci) => ci.contract_item_id === "ci-1");
  });
});

afterEach(() => vi.unstubAllGlobals());

const result = () => packageJson(getDb(), readiness(getDb(), "clm-7"));

test.each<MatchStatus>(["confirmed", "suggested", "rejected"])("only confirmed links enter approved evidence: %s", (status) => {
  reviewMatch("em-1", status);
  const pack = result();
  expect(pack.items[0].evidence).toHaveLength(status === "confirmed" ? 1 : 0);
  expect(pack.annexure).toHaveLength(status === "confirmed" ? 1 : 0);
  if (status === "confirmed") {
    expect(pack.items[0].evidence[0]).toMatchObject({ evidence_id: "ev-1", approved_support: true, annexure_ref: "A1" });
  } else {
    expect(pack.items[0].support_gaps).toContain("No confirmed evidence support");
  }
  expect(pack.items[0].unreviewed_evidence.suggestions).toHaveLength(status === "suggested" ? 1 : 0);
  expect(pack.items[0].unreviewed_evidence.label).toContain("NOT APPROVED SUPPORT");
});

test("archived, removed and unlinked evidence never enter the annexure", () => {
  commit((d) => { d.evidence.find((e) => e.id === "ev-1")!.archived = true; });
  expect(result().annexure).toEqual([]);
  commit((d) => { d.evidence = d.evidence.filter((e) => e.id !== "ev-1"); });
  expect(result().annexure).toEqual([]);
  expect(result().items[0].evidence).toEqual([]);
});

test("weak and partial support gaps come directly from readiness", () => {
  commit((d) => {
    d.evidence_matches[0].assessment = "weak";
    d.evidence_matches[0].missing_evidence = ["date confirmation"];
  });
  expect(result().items[0].evidence_status).toBe("weak");
  expect(result().items[0].support_gaps).toEqual(readiness(getDb(), "clm-7").rows[0].supportGaps);
  commit((d) => { d.evidence_matches[0].assessment = "strong"; });
  expect(result().items[0]).toMatchObject({ evidence_status: "partial", support_gaps: ["date confirmation"] });
});

test("current claim amounts, items and identification are exported without fabricated references", () => {
  commit((d) => { d.claim_items[0].claimed_amount = 123.45; });
  const pack = result();
  expect(pack.title).toBe(PACKAGE_TITLE);
  expect(pack.project).toMatchObject({ id: "prj-hume", name: "Hume St Tower" });
  expect(pack.claim).toMatchObject({ id: "clm-7", number: 7, total_claimed: 123.45 });
  expect(pack.items).toHaveLength(1);
  expect(pack.items[0]).toMatchObject({ contract_item_id: "ci-1", claimed_amount: 123.45 });
  expect(pack.annexure.every((entry) => getDb().evidence.some((ev) => ev.id === entry.evidence_id))).toBe(true);
  expect(pack.items[0].evidence[0].annexure_ref).toBe(pack.annexure[0].ref);
});

test("shared evidence is numbered once and generation does not alter the stored data", () => {
  commit((d) => {
    d.claim_items.push({ ...d.claim_items[0], id: "second-claim-item", contract_item_id: "ci-2" });
    d.evidence_matches.push({ ...d.evidence_matches[0], id: "second-link", contract_item_id: "ci-2" });
  });
  const before = structuredClone(getDb());
  const pack = result();
  expect(pack.annexure).toHaveLength(1);
  expect(pack.items.map((item) => item.evidence[0].annexure_ref)).toEqual(["A1", "A1"]);
  expect(getDb()).toEqual(before);
});

test("reopening removes approved support from exports loaded from localStorage", async () => {
  expect(result().items[0].evidence).toHaveLength(1);
  reviewMatch("em-1", "suggested");
  vi.resetModules();
  const reloaded = await import("./store");
  const db = reloaded.getDb();
  const pack = packageJson(db, readiness(db, "clm-7"));
  expect(pack.items[0].evidence).toEqual([]);
  expect(pack.annexure).toEqual([]);
  expect(pack.items[0].evidence_status).toBe("missing");
});

test("all exported annexure entries belong to this claim's project", () => {
  const db = getDb();
  expect(annexure(db, readiness(db, "clm-7")).every((entry) => entry.ev.project_id === "prj-hume")).toBe(true);
});
