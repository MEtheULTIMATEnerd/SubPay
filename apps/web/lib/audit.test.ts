import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("./env", () => ({ LIVE: false }));

import { read, readiness, recordExport, reviewMatch } from "./api";
import { packageJson } from "./claim-package";
import { commit, getDb, resetDb } from "./store";

beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value),
  });
  resetDb({ profile_id: "usr-ollie" });
});

afterEach(() => vi.unstubAllGlobals());

test.each(["confirmed", "rejected"] as const)("%s review records actor and complete match references", (status) => {
  reviewMatch("em-7", status);
  const event = getDb().audit_events[0];
  expect(event).toMatchObject({
    action: `match.${status}`, actor_id: "usr-ollie", project_id: "prj-hume",
    entity: "evidence_match", entity_id: "em-7",
    metadata: {
      evidence: "EV-007", evidence_id: "ev-7", item: "22.3",
      contract_item_id: "ci-11", match_id: "em-7",
      previous_status: "suggested", new_status: status,
    },
  });
  expect(Number.isNaN(Date.parse(event.created_at))).toBe(false);
});

test.each(["confirmed", "rejected"] as const)("reopening a %s match adds a new event and preserves history", (status) => {
  reviewMatch("em-7", status);
  const history = structuredClone(getDb().audit_events);
  reviewMatch("em-7", "suggested");
  expect(getDb().audit_events[0]).toMatchObject({
    action: "match.reopened", metadata: { previous_status: status, new_status: "suggested" },
  });
  expect(getDb().audit_events.slice(1)).toEqual(history);
});

test("unchanged review status does not create another decision event", () => {
  const history = structuredClone(getDb().audit_events);
  reviewMatch("em-1", "confirmed");
  expect(getDb().audit_events).toEqual(history);
});

test("JSON download initiation records claim, format and actor", () => {
  recordExport("clm-7", "json");
  expect(getDb().audit_events[0]).toMatchObject({
    action: "package.download_initiated", entity: "claim", entity_id: "clm-7",
    actor_id: "usr-ollie", project_id: "prj-hume",
    metadata: { claim_id: "clm-7", format: "json", outcome: "download_initiated" },
  });
});

test("printing records initiation without claiming a PDF was saved", () => {
  recordExport("clm-7", "pdf");
  expect(getDb().audit_events[0]).toMatchObject({
    action: "package.print_initiated", entity_id: "clm-7",
    metadata: { claim_id: "clm-7", format: "pdf", outcome: "print_initiated" },
  });
  expect(getDb().claims.find((c) => c.id === "clm-7")!.status).toBe("draft");
});

test("failed reviews and exports leave history unchanged", () => {
  const history = structuredClone(getDb().audit_events);
  expect(() => reviewMatch("missing", "confirmed")).toThrow("Match not found");
  expect(() => recordExport("missing", "json")).toThrow("Claim not found");
  expect(getDb().audit_events).toEqual(history);
});

test("another organisation cannot read or append project events", () => {
  commit((d) => { d.session = { profile_id: "usr-other" }; });
  const history = structuredClone(getDb().audit_events);
  expect(() => read.audit(getDb(), "prj-hume")).toThrow("Project not found");
  expect(() => reviewMatch("em-7", "confirmed")).toThrow("Project not found");
  expect(() => recordExport("clm-7", "json")).toThrow("Project not found");
  expect(getDb().audit_events).toEqual(history);
});

test("reading audit, readiness and package previews creates no events", () => {
  const history = structuredClone(getDb().audit_events);
  read.audit(getDb(), "prj-hume");
  packageJson(getDb(), readiness(getDb(), "clm-7"));
  expect(getDb().audit_events).toEqual(history);
});

test("events survive a fresh localStorage load and stay scoped to their project", async () => {
  reviewMatch("em-7", "rejected");
  recordExport("clm-7", "json");
  const history = structuredClone(getDb().audit_events);
  vi.resetModules();
  const reloaded = await import("./store");
  expect(reloaded.getDb().audit_events).toEqual(history);
  expect(read.audit(reloaded.getDb(), "prj-dock")).toEqual([]);
  expect(read.audit(reloaded.getDb(), "prj-hume")).toHaveLength(history.length);
});
