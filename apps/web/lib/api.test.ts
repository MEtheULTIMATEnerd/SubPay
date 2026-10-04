import { beforeEach, expect, test } from "vitest";
import * as api from "./api";
import { getDb, resetDb } from "./store";
import { matchEvidence } from "./ai";

beforeEach(() => resetDb({ profile_id: "usr-ollie" }));

test("rejects unauthenticated access", () => {
  api.signOut();
  expect(() => api.createProject({ name: "X", client_name: "Y", site_address: "", start_date: null, end_date: null })).toThrow("Not signed in");
});

test("organisation isolation: other org's projects are invisible and unwritable", () => {
  const db = getDb();
  expect(api.read.projects(db).map((p) => p.id)).not.toContain("prj-secret");
  expect(api.read.project(db, "prj-secret")).toBeNull();
  expect(() => api.setProjectStatus("prj-secret", "archived")).toThrow("Project not found");
});

test("project create, update, archive", () => {
  const id = api.createProject({ name: "Test", client_name: "Builder", site_address: "", start_date: null, end_date: null });
  api.updateProject(id, { name: "Renamed", client_name: "Builder", site_address: "1 St", start_date: null, end_date: null });
  api.setProjectStatus(id, "archived");
  const p = api.read.project(getDb(), id)!;
  expect([p.name, p.status, p.organisation_id]).toEqual(["Renamed", "archived", "org-kearney"]);
});

test("contract upload validates type and extraction creates draft items", () => {
  expect(() => api.uploadContract("prj-hume", { name: "a.exe", type: "application/x-msdownload", size: 10 })).toThrow("PDF or DOCX");
  const cid = api.uploadContract("prj-hume", { name: "new.pdf", type: "application/pdf", size: 1000 });
  api.runExtraction(cid);
  const items = api.read.contractItems(getDb(), cid);
  expect(items.length).toBeGreaterThan(0);
  expect(items.every((i) => i.review_status === "draft")).toBe(true);
});

test("human edit is flagged and audited", () => {
  api.updateContractItem("ci-1", { quantity: 999 });
  const db = getDb();
  expect(db.contract_items.find((i) => i.id === "ci-1")!.edited_by_human).toBe(true);
  expect(db.audit_events[0].action).toBe("contract_item.edited");
});

test("confirming a match moves readiness; rejecting does not", () => {
  const before = api.readiness(getDb(), "clm-7");
  const row = before.rows.find((r) => r.item.item_code === "14.5")!;
  expect(row.state).toBe("partial");
  api.reviewMatch("em-7", "rejected"); // crane timesheet → 22.3
  expect(api.readiness(getDb(), "clm-7").rows.find((r) => r.item.item_code === "22.3")!.state).toBe("missing");
  api.linkEvidence("ev-6", "ci-3"); // human links photo to 14.4 soffit
  const after = api.readiness(getDb(), "clm-7");
  expect(after.rows.find((r) => r.item.item_code === "14.4")!.state).toBe("strong");
  expect(after.coverage).toBeGreaterThan(before.coverage);
});

test("mock AI matching is deterministic and never 'verified'", () => {
  const items = getDb().contract_items;
  const ev = { id: "x", title: "Site photo", description: "Edge beam formwork level 3 grid C5", evidence_type: "photo" as const };
  const a = matchEvidence(ev, items);
  expect(a).toEqual(matchEvidence(ev, items));
  expect(a.matches[0].contract_item_id).toBe("ci-1");
  expect(["strong", "partial", "weak"]).toContain(a.matches[0].assessment);
});

test("AI outage fails processing but manual linking still works", () => {
  api.setAiAvailable(false);
  const id = api.uploadEvidence("prj-hume", { file: null, title: "Note", description: "extra drainage", evidence_type: "message", captured_at: new Date().toISOString(), location: null, thumbnail: null });
  api.runMatching(id);
  expect(getDb().evidence.find((e) => e.id === id)!.processing_status).toBe("failed");
  api.linkEvidence(id, "ci-3");
  expect(getDb().evidence_matches.some((m) => m.evidence_id === id && m.status === "confirmed")).toBe(true);
});
