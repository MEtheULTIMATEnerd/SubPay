// Demo mode: contracts are simulated in the browser, as in the original prototype.
import { beforeEach, expect, test, vi } from "vitest";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("./env", () => ({ LIVE: false, API_URL: "", SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }));
vi.mock("./http", () => ({ apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("Supabase must not be used in demo mode"); } }));

import { read, runExtraction } from "./api";
import { getContractDownloadUrl, refreshContracts, reviewContractItem, updateContractItem, uploadContract } from "./contracts";
import { getDb, resetDb } from "./store";

beforeEach(() => resetDb({ profile_id: "usr-ollie" }));

test("demo mode uploads, extracts and reviews locally without calling the API", async () => {
  const file = new File([new Uint8Array(100)], "New_Subcontract.pdf", { type: "application/pdf" });
  const id = await uploadContract("prj-hume", file);
  runExtraction(id); // the demo runs this on a timer; call it directly here
  await refreshContracts("prj-hume");

  const items = read.contractItems(getDb(), id);
  expect(items.length).toBeGreaterThan(0);

  await updateContractItem(items[0].id, { quantity: 999 });
  await reviewContractItem(items[0].id, "confirmed");
  expect(getDb().contract_items.find((i) => i.id === items[0].id)).toMatchObject({ quantity: 999, edited_by_human: true, review_status: "confirmed" });

  await expect(getContractDownloadUrl(id)).resolves.toBeNull(); // demo mode stores no files
  expect(apiFetch).not.toHaveBeenCalled();
});

test("demo mode surfaces upload validation as a rejected promise", async () => {
  const file = new File(["x"], "a.exe", { type: "application/x-msdownload" });
  await expect(uploadContract("prj-hume", file)).rejects.toThrow("PDF or DOCX");
});
