// Live mode: contracts, items and review go through the API. The API is replaced by a fake.
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./env", () => ({ LIVE: true, API_URL: "http://api.test", SUPABASE_URL: "http://supabase.test", SUPABASE_ANON_KEY: "anon" }));
vi.mock("./http", () => ({ apiFetch: mocks.apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("not used"); } }));

import { read } from "./api";
import { getContractDownloadUrl, refreshContracts, retryExtraction, reviewContractItem, updateContractItem, uploadContract } from "./contracts";
import { ApiError } from "./errors";
import { commit, getDb, resetDb } from "./store";
import type { Contract, ContractItem } from "./types";

const USER_ID = "a0000000-0000-4000-8000-000000000001";
const ORG_ID = "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01";
const PROJECT_ID = "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22";
const CONTRACT_ID = "cccccccc-0000-4000-8000-000000000001";
const at = "2026-10-04T05:00:00Z";

const contract = (over: Partial<Contract> = {}): Contract => ({
  id: CONTRACT_ID, project_id: PROJECT_ID, original_filename: "Subcontract.pdf", storage_path: `contracts/${PROJECT_ID}/${CONTRACT_ID}/original.pdf`,
  mime_type: "application/pdf", size_bytes: 1000, page_count: null, processing_status: "ready", error: null, uploaded_by: USER_ID,
  created_at: at, updated_at: at, processed_at: at, ...over,
});
const item = (over: Partial<ContractItem> = {}): ContractItem => ({
  id: "item-1", contract_id: CONTRACT_ID, item_code: "2.1", description: "Formwork, slab edges", quantity: 180, unit: "m²", rate: 75, amount: 13500,
  conditions: null, notice_requirement: null, due_date: null, extraction_confidence: 0.9, review_status: "draft", edited_by_human: false,
  reviewed_by: null, source_reference: "Schedule of rates, item 2.1", extracted_values: { quantity: 180 }, sort_order: 1, created_at: at, updated_at: at, ...over,
});
const pdf = (name = "Subcontract.pdf", size = 1000, type = "application/pdf") => new File([new Uint8Array(size)], name, { type });

/** Answer API calls by path. Unlisted paths fail the test loudly. */
function api(routes: Record<string, unknown | (() => unknown)>) {
  mocks.apiFetch.mockImplementation(async (path: string) => {
    if (!(path in routes)) throw new Error(`unexpected API call: ${path}`);
    const answer = routes[path];
    return typeof answer === "function" ? (answer as () => unknown)() : answer;
  });
}
const calls = (path: string) => mocks.apiFetch.mock.calls.filter(([p]) => p === path);

beforeEach(() => {
  mocks.apiFetch.mockReset();
  resetDb(null);
  commit((d) => {
    d.organisations.push({ id: ORG_ID, name: "Org A Formwork", created_at: at, updated_at: at });
    d.profiles.push({ id: USER_ID, organisation_id: ORG_ID, email: "alex@subpay.test", full_name: "Alex Owner", role: "owner", created_at: at, updated_at: at });
    d.projects.push({ id: PROJECT_ID, organisation_id: ORG_ID, name: "Real Tower", client_name: "Builder", site_address: "", status: "active", start_date: null, end_date: null, created_by: USER_ID, created_at: at, updated_at: at });
    d.session = { profile_id: USER_ID };
  });
});
afterEach(() => vi.useRealTimers());

test("refresh loads the project's contracts and their items, replacing the old copy", async () => {
  commit((d) => {
    d.contracts.push(contract({ id: "stale" }));
    d.contract_items.push(item({ id: "stale-item", contract_id: "stale" }));
  });
  const seeded = getDb().contracts.filter((c) => c.project_id !== PROJECT_ID).length;
  api({
    [`/projects/${PROJECT_ID}/contracts`]: { items: [contract()] },
    [`/contracts/${CONTRACT_ID}/items`]: { items: [item(), item({ id: "item-2", item_code: "2.2" })] },
  });

  await refreshContracts(PROJECT_ID);

  expect(read.contracts(getDb(), PROJECT_ID).map((c) => c.id)).toEqual([CONTRACT_ID]);
  expect(read.contractItems(getDb(), CONTRACT_ID).map((i) => i.item_code)).toEqual(["2.1", "2.2"]);
  expect(getDb().contract_items.some((i) => i.id === "stale-item")).toBe(false);
  expect(getDb().contracts.filter((c) => c.project_id !== PROJECT_ID)).toHaveLength(seeded); // other data untouched
});

test("upload sends the file as a form and then follows extraction until the items arrive", async () => {
  vi.useFakeTimers();
  let status: Contract["processing_status"] = "processing";
  api({
    [`/projects/${PROJECT_ID}/contracts`]: contract({ processing_status: "processing", processed_at: null }),
    [`/contracts/${CONTRACT_ID}`]: () => ({ ...contract({ processing_status: status }), download_url: "https://signed.test/x" }),
    [`/contracts/${CONTRACT_ID}/items`]: { items: [item()] },
  });

  const id = await uploadContract(PROJECT_ID, pdf());
  expect(id).toBe(CONTRACT_ID);

  const [, options] = calls(`/projects/${PROJECT_ID}/contracts`)[0];
  expect(options.method).toBe("POST");
  expect(options.form).toBeInstanceOf(FormData);
  expect((options.form.get("file") as File).name).toBe("Subcontract.pdf");

  // shown straight away as processing, with no items yet
  expect(read.contract(getDb(), CONTRACT_ID)?.processing_status).toBe("processing");
  expect(read.contractItems(getDb(), CONTRACT_ID)).toEqual([]);

  await vi.advanceTimersByTimeAsync(1600); // first check: still processing
  expect(read.contract(getDb(), CONTRACT_ID)?.processing_status).toBe("processing");

  status = "ready";
  await vi.advanceTimersByTimeAsync(1600); // second check: ready
  expect(read.contract(getDb(), CONTRACT_ID)?.processing_status).toBe("ready");
  expect(read.contractItems(getDb(), CONTRACT_ID)).toHaveLength(1);
  expect("download_url" in read.contract(getDb(), CONTRACT_ID)!).toBe(false); // short-lived links are not kept

  const polls = calls(`/contracts/${CONTRACT_ID}`).length;
  await vi.advanceTimersByTimeAsync(10_000);
  expect(calls(`/contracts/${CONTRACT_ID}`).length).toBe(polls); // stops once finished
});

test("a failed extraction is shown, and stops being followed", async () => {
  vi.useFakeTimers();
  api({
    [`/projects/${PROJECT_ID}/contracts`]: contract({ processing_status: "processing" }),
    [`/contracts/${CONTRACT_ID}`]: contract({ processing_status: "failed", error: "AI analysis unavailable. Retry, or continue reviewing manually." }),
  });
  await uploadContract(PROJECT_ID, pdf());
  await vi.advanceTimersByTimeAsync(1600);

  expect(read.contract(getDb(), CONTRACT_ID)).toMatchObject({ processing_status: "failed", error: expect.stringContaining("AI analysis unavailable") });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(calls(`/contracts/${CONTRACT_ID}`)).toHaveLength(1);
});

test("obviously wrong files are refused before any request", async () => {
  await expect(uploadContract(PROJECT_ID, pdf("virus.exe", 10, "application/x-msdownload"))).rejects.toThrow("Only PDF or DOCX contracts are supported");
  await expect(uploadContract(PROJECT_ID, pdf("huge.pdf", 25 * 1024 * 1024 + 1))).rejects.toThrow("Contract must be 25 MB or smaller");
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("an upload the API rejects leaves nothing behind", async () => {
  mocks.apiFetch.mockRejectedValue(new ApiError(415, "Only PDF or DOCX contracts are supported", "unsupported_media_type"));
  await expect(uploadContract(PROJECT_ID, pdf("renamed.pdf"))).rejects.toThrow("Only PDF or DOCX");
  expect(read.contracts(getDb(), PROJECT_ID)).toEqual([]);
});

test("retry restarts extraction and follows it again", async () => {
  vi.useFakeTimers();
  commit((d) => { d.contracts.push(contract({ processing_status: "failed", error: "AI analysis unavailable." })); });
  api({
    [`/contracts/${CONTRACT_ID}/extract`]: contract({ processing_status: "processing", error: null }),
    [`/contracts/${CONTRACT_ID}`]: contract(),
    [`/contracts/${CONTRACT_ID}/items`]: { items: [item()] },
  });

  await retryExtraction(CONTRACT_ID);
  expect(calls(`/contracts/${CONTRACT_ID}/extract`)[0][1]).toEqual({ method: "POST" });
  expect(read.contract(getDb(), CONTRACT_ID)).toMatchObject({ processing_status: "processing", error: null });

  await vi.advanceTimersByTimeAsync(1600);
  expect(read.contract(getDb(), CONTRACT_ID)?.processing_status).toBe("ready");
  expect(read.contractItems(getDb(), CONTRACT_ID)).toHaveLength(1);
});

test("editing sends only the fields that changed", async () => {
  commit((d) => { d.contracts.push(contract()); d.contract_items.push(item()); });
  api({ "/contract-items/item-1": item({ quantity: 200, amount: 15000, edited_by_human: true }) });

  await updateContractItem("item-1", { description: "Formwork, slab edges", quantity: 200, unit: "m²", rate: 75, amount: 15000, conditions: null, notice_requirement: null, due_date: null });

  expect(mocks.apiFetch).toHaveBeenCalledWith("/contract-items/item-1", { method: "PATCH", body: { quantity: 200, amount: 15000 } });
  expect(getDb().contract_items.find((i) => i.id === "item-1")).toMatchObject({ quantity: 200, edited_by_human: true });
  const audit = read.audit(getDb(), PROJECT_ID)[0];
  expect(audit.action).toBe("contract_item.edited");
  expect(audit.metadata).toMatchObject({ fields: ["quantity", "amount"], before: { quantity: 180, amount: 13500 } });
});

test("saving without changing anything makes no request", async () => {
  commit((d) => { d.contracts.push(contract()); d.contract_items.push(item()); });
  await updateContractItem("item-1", { description: "Formwork, slab edges", quantity: 180, unit: "m²" });
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("confirm, reject and reopen use their own endpoints", async () => {
  commit((d) => { d.contracts.push(contract()); d.contract_items.push(item()); });
  const stored = () => getDb().contract_items.find((i) => i.id === "item-1")!;

  api({ "/contract-items/item-1/confirm": item({ review_status: "confirmed", reviewed_by: USER_ID }) });
  await reviewContractItem("item-1", "confirmed");
  expect(stored()).toMatchObject({ review_status: "confirmed", reviewed_by: USER_ID });

  api({ "/contract-items/item-1/reject": item({ review_status: "rejected", reviewed_by: USER_ID }) });
  await reviewContractItem("item-1", "rejected");
  expect(stored().review_status).toBe("rejected");

  api({ "/contract-items/item-1/reopen": item() });
  await reviewContractItem("item-1", "draft");
  expect(stored()).toMatchObject({ review_status: "draft", reviewed_by: null });
  expect(mocks.apiFetch.mock.calls.every(([, options]) => options.method === "POST")).toBe(true);
});

test("an API error during review leaves the item as it was", async () => {
  commit((d) => { d.contracts.push(contract()); d.contract_items.push(item()); });
  mocks.apiFetch.mockRejectedValue(new ApiError(404, "Contract item not found", "not_found"));
  await expect(reviewContractItem("item-1", "confirmed")).rejects.toThrow("Contract item not found");
  expect(getDb().contract_items.find((i) => i.id === "item-1")?.review_status).toBe("draft");
});

test("a download link is fetched fresh each time and never stored", async () => {
  api({ [`/contracts/${CONTRACT_ID}`]: { ...contract(), download_url: "https://signed.test/original.pdf?token=abc" } });
  await expect(getContractDownloadUrl(CONTRACT_ID)).resolves.toBe("https://signed.test/original.pdf?token=abc");
  expect(JSON.stringify(getDb())).not.toContain("signed.test");
});
