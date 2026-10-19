import { expect, test, vi } from "vitest";

vi.mock("./env", () => ({ LIVE: true }));

import { readiness, recordExport } from "./api";
import { packageJson } from "./claim-package";
import type { Readiness } from "./api";
import { seed } from "./seed";

test("live mode cannot expose demo claim readiness even with cached demo claims", () => {
  const db = seed();
  db.session = { profile_id: "usr-ollie" };
  expect(() => readiness(db, "clm-7")).toThrow("Live claim readiness is not available yet");
});

test("live mode cannot generate a package from a cached demo readiness snapshot", () => {
  const db = seed();
  expect(() => packageJson(db, { rows: [], claim: db.claims[0] } as unknown as Readiness)).toThrow("Live claim packages are not available yet");
});

test("live mode cannot record a local demo export as audit history", () => {
  expect(() => recordExport("clm-7", "json")).toThrow("Live audit is not available yet");
});
