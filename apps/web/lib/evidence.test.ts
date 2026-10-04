// Live mode: evidence goes through the API. The API is replaced by a fake.
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./env", () => ({ LIVE: true, API_URL: "http://api.test", SUPABASE_URL: "http://supabase.test", SUPABASE_ANON_KEY: "anon" }));
vi.mock("./http", () => ({ apiFetch: mocks.apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("not used"); } }));

import { read, setAiAvailable } from "./api";
import { ApiError } from "./errors";
import {
  getEvidenceDownloadUrl, previewFailed, previewOf, refreshEvidence, rerunMatching, resetEvidenceState, setEvidenceArchived, updateEvidence, uploadEvidence,
  type EvidenceInput,
} from "./evidence";
import { clearCachedProjects } from "./projects";
import { commit, getDb, resetDb } from "./store";
import type { Evidence } from "./types";

const USER_ID = "a0000000-0000-4000-8000-000000000001";
const ORG_ID = "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01";
const PROJECT_ID = "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22";
const EVIDENCE_ID = "eeeeeeee-0000-4000-8000-000000000001";
const at = "2026-10-04T05:00:00Z";
const SIGNED = "https://signed.test/evidence/original.jpg?token=abc";

type ApiEvidence = Omit<Evidence, "thumbnail"> & { preview_url: string | null; download_url?: string | null };

const record = (over: Partial<ApiEvidence> = {}): ApiEvidence => ({
  id: EVIDENCE_ID, project_id: PROJECT_ID, code: "EV-001", uploaded_by: USER_ID,
  storage_path: `evidence/${PROJECT_ID}/${EVIDENCE_ID}/original.jpg`, original_filename: "IMG_2041.jpg", mime_type: "image/jpeg", size_bytes: 2048,
  evidence_type: "photo", captured_at: "2026-09-14T01:30:00Z", title: "Level 3 slab pour", description: "East side poured.",
  metadata: { location: "Level 3", source: "mobile_upload", tags: [], author: "Alex Owner" },
  processing_status: "ready", archived: false, created_at: at, updated_at: at, preview_url: SIGNED, ...over,
});
/** What the local store holds for a record: no signed links. */
const local = (over: Partial<ApiEvidence> = {}): Evidence => {
  const copy: Partial<ApiEvidence> = record(over);
  delete copy.preview_url;
  delete copy.download_url;
  return { ...(copy as Omit<Evidence, "thumbnail">), thumbnail: null };
};
const photo = (name = "IMG_2041.jpg", size = 2048, type = "image/jpeg") => new File([new Uint8Array(size)], name, { type });
const input = (over: Partial<EvidenceInput> = {}): EvidenceInput => ({
  file: photo(), title: "Level 3 slab pour", description: "East side poured.", evidence_type: "photo",
  captured_at: "2026-09-14T01:30:00.000Z", location: "Level 3", thumbnail: "data:image/jpeg;base64,AAAA", source: "mobile_upload", ...over,
});

/** Answer API calls by path. Unlisted paths fail the test loudly. */
type Options = { query?: Record<string, number> };
function api(routes: Record<string, unknown | ((options: Options) => unknown)>) {
  mocks.apiFetch.mockImplementation(async (path: string, options: Options = {}) => {
    if (!(path in routes)) throw new Error(`unexpected API call: ${path}`);
    const answer = routes[path];
    return typeof answer === "function" ? (answer as (options: Options) => unknown)(options) : answer;
  });
}
const calls = (path: string) => mocks.apiFetch.mock.calls.filter(([p]) => p === path);
const stored = (id = EVIDENCE_ID) => getDb().evidence.find((e) => e.id === id);

beforeEach(() => {
  mocks.apiFetch.mockReset();
  resetEvidenceState();
  resetDb(null);
  commit((d) => {
    d.organisations.push({ id: ORG_ID, name: "Org A Formwork", created_at: at, updated_at: at });
    d.profiles.push({ id: USER_ID, organisation_id: ORG_ID, email: "alex@subpay.test", full_name: "Alex Owner", role: "owner", created_at: at, updated_at: at });
    d.projects.push({ id: PROJECT_ID, organisation_id: ORG_ID, name: "Real Tower", client_name: "Builder", site_address: "", status: "active", start_date: null, end_date: null, created_by: USER_ID, created_at: at, updated_at: at });
    d.session = { profile_id: USER_ID };
  });
});
afterEach(() => vi.useRealTimers());

test("refresh pages through the project's evidence and replaces the old copy", async () => {
  commit((d) => { d.evidence.push(local({ id: "stale", code: "EV-099" })); });
  const elsewhere = getDb().evidence.filter((e) => e.project_id !== PROJECT_ID).length;
  const firstPage = Array.from({ length: 200 }, (_, i) => record({ id: `ev-${i}`, code: `EV-${String(i + 1).padStart(3, "0")}`, preview_url: null }));
  api({
    [`/projects/${PROJECT_ID}/evidence`]: ({ query }: Options) => ({ items: query!.offset === 0 ? firstPage : [record({ code: "EV-201" })] }),
  });

  await refreshEvidence(PROJECT_ID);

  expect(calls(`/projects/${PROJECT_ID}/evidence`).map(([, o]) => o.query)).toEqual([{ limit: 200, offset: 0 }, { limit: 200, offset: 200 }]);
  expect(read.evidence(getDb(), PROJECT_ID)).toHaveLength(201);
  expect(stored("stale")).toBeUndefined();
  expect(getDb().evidence.filter((e) => e.project_id !== PROJECT_ID)).toHaveLength(elsewhere); // other data untouched
});

test("signed preview links are shown but never written to the browser's storage", async () => {
  api({ [`/projects/${PROJECT_ID}/evidence`]: { items: [record(), record({ id: "note", storage_path: null, original_filename: null, mime_type: null, preview_url: null })] } });
  await refreshEvidence(PROJECT_ID);

  expect(previewOf(stored()!)).toBe(SIGNED);
  expect(previewOf(stored("note")!)).toBeNull();
  expect(stored()).toMatchObject({ thumbnail: null });
  expect("preview_url" in stored()!).toBe(false);
  expect(JSON.stringify(getDb())).not.toContain("signed.test");
});

test("upload sends the file and its details as a form, then follows processing and suggests matches", async () => {
  vi.useFakeTimers();
  let status: Evidence["processing_status"] = "processing";
  api({
    [`/projects/${PROJECT_ID}/evidence`]: record({ processing_status: "processing" }),
    [`/evidence/${EVIDENCE_ID}`]: () => ({ ...record({ processing_status: status }), download_url: "https://signed.test/download" }),
  });

  const id = await uploadEvidence(PROJECT_ID, input());
  expect(id).toBe(EVIDENCE_ID);

  const [, options] = calls(`/projects/${PROJECT_ID}/evidence`)[0];
  const form = options.form as FormData;
  expect(options.method).toBe("POST");
  expect((form.get("file") as File).name).toBe("IMG_2041.jpg");
  expect(form.get("title")).toBe("Level 3 slab pour");
  expect(form.get("description")).toBe("East side poured.");
  expect(form.get("evidence_type")).toBe("photo");
  expect(form.get("captured_at")).toBe("2026-09-14T01:30:00.000Z");
  expect(JSON.parse(form.get("metadata") as string)).toEqual({ location: "Level 3", source: "mobile_upload", tags: [], author: "Alex Owner" });
  // The API works out who and which organisation from the session, and names the stored file itself.
  expect([...form.keys()].sort()).toEqual(["captured_at", "description", "evidence_type", "file", "metadata", "title"]);

  // shown straight away as processing, with its preview
  expect(stored()).toMatchObject({ processing_status: "processing", code: "EV-001", thumbnail: null });
  expect(previewOf(stored()!)).toBe(SIGNED);
  expect(read.audit(getDb(), PROJECT_ID)[0]).toMatchObject({ action: "evidence.uploaded", entity_id: EVIDENCE_ID });

  await vi.advanceTimersByTimeAsync(1600); // first check: still processing
  expect(stored()?.processing_status).toBe("processing");

  status = "ready";
  await vi.advanceTimersByTimeAsync(1600); // second check: ready
  expect(stored()?.processing_status).toBe("ready");
  expect(read.audit(getDb(), PROJECT_ID).some((a) => a.action === "match.generated" && a.entity_id === EVIDENCE_ID)).toBe(true);
  expect(JSON.stringify(getDb())).not.toContain("signed.test");

  const polls = calls(`/evidence/${EVIDENCE_ID}`).length;
  await vi.advanceTimersByTimeAsync(10_000);
  expect(calls(`/evidence/${EVIDENCE_ID}`).length).toBe(polls); // stops once finished
});

test("a written note is sent without a file", async () => {
  api({ [`/projects/${PROJECT_ID}/evidence`]: record({ storage_path: null, original_filename: null, mime_type: null, size_bytes: null, evidence_type: "message", title: "Note", preview_url: null }) });
  await uploadEvidence(PROJECT_ID, input({ file: null, title: "", evidence_type: "message", description: "  Super confirmed the north wall by phone. " }));

  const form = calls(`/projects/${PROJECT_ID}/evidence`)[0][1].form as FormData;
  expect(form.has("file")).toBe(false);
  expect(form.has("title")).toBe(false); // the API picks the default title
  expect(form.get("description")).toBe("Super confirmed the north wall by phone.");
  expect(stored()).toMatchObject({ storage_path: null, title: "Note" });
});

test("when the person links the evidence themselves, no suggestions are generated", async () => {
  vi.useFakeTimers();
  api({ [`/projects/${PROJECT_ID}/evidence`]: record({ processing_status: "processing" }), [`/evidence/${EVIDENCE_ID}`]: record() });
  await uploadEvidence(PROJECT_ID, input(), { autoMatch: false });
  await vi.advanceTimersByTimeAsync(1600);

  expect(stored()?.processing_status).toBe("ready");
  expect(read.audit(getDb(), PROJECT_ID).some((a) => a.action === "match.generated")).toBe(false);
});

test("failed processing is shown, keeps the evidence, and stops being followed", async () => {
  vi.useFakeTimers();
  api({ [`/projects/${PROJECT_ID}/evidence`]: record({ processing_status: "processing" }), [`/evidence/${EVIDENCE_ID}`]: record({ processing_status: "failed" }) });
  await uploadEvidence(PROJECT_ID, input());
  await vi.advanceTimersByTimeAsync(1600);

  expect(stored()).toMatchObject({ processing_status: "failed", title: "Level 3 slab pour" });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(calls(`/evidence/${EVIDENCE_ID}`)).toHaveLength(1);
});

test("obviously wrong uploads are refused before any request", async () => {
  await expect(uploadEvidence(PROJECT_ID, input({ file: null, description: "   " }))).rejects.toThrow("Add a file or a written note");
  await expect(uploadEvidence(PROJECT_ID, input({ file: photo("virus.exe", 10, "application/x-msdownload") }))).rejects.toThrow("That file type is not supported");
  await expect(uploadEvidence(PROJECT_ID, input({ file: photo("clip.mp4", 10, "video/mp4") }))).rejects.toThrow("That file type is not supported");
  await expect(uploadEvidence(PROJECT_ID, input({ file: photo("huge.jpg", 50 * 1024 * 1024 + 1) }))).rejects.toThrow("Evidence files must be 50 MB or smaller");
  await expect(uploadEvidence(PROJECT_ID, input({ title: "x".repeat(201) }))).rejects.toThrow("Title must be 200 characters or fewer");
  await expect(uploadEvidence(PROJECT_ID, input({ description: "x".repeat(5001) }))).rejects.toThrow("Description must be 5000 characters or fewer");
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("a camera photo with no file extension is still accepted", async () => {
  api({ [`/projects/${PROJECT_ID}/evidence`]: record() });
  await expect(uploadEvidence(PROJECT_ID, input({ file: photo("image", 10, "image/jpeg") }))).resolves.toBe(EVIDENCE_ID);
});

test("an upload the API rejects leaves nothing behind", async () => {
  mocks.apiFetch.mockRejectedValue(new ApiError(415, "That file type is not supported.", "unsupported_media_type"));
  await expect(uploadEvidence(PROJECT_ID, input({ file: photo("renamed.jpg") }))).rejects.toThrow("That file type is not supported");
  expect(read.evidence(getDb(), PROJECT_ID)).toEqual([]);
});

test("editing sends only what changed and keeps the rest of the metadata", async () => {
  commit((d) => { d.evidence.push(local()); });
  api({ [`/evidence/${EVIDENCE_ID}`]: record({ title: "Level 3 slab pour (east)", metadata: { location: "Level 3 east", source: "mobile_upload", tags: [], author: "Alex Owner" } }) });

  await updateEvidence(EVIDENCE_ID, { title: " Level 3 slab pour (east) ", description: "East side poured.", evidence_type: "photo", location: "Level 3 east" });

  expect(mocks.apiFetch).toHaveBeenCalledWith(`/evidence/${EVIDENCE_ID}`, {
    method: "PATCH",
    body: { title: "Level 3 slab pour (east)", metadata: { location: "Level 3 east", source: "mobile_upload", tags: [], author: "Alex Owner" } },
  });
  expect(stored()).toMatchObject({ title: "Level 3 slab pour (east)", metadata: { location: "Level 3 east" } });
  expect(read.audit(getDb(), PROJECT_ID)[0]).toMatchObject({ action: "evidence.edited", metadata: { evidence: "EV-001", fields: ["title", "metadata"] } });
});

test("saving without changing anything makes no request", async () => {
  commit((d) => { d.evidence.push(local()); });
  await updateEvidence(EVIDENCE_ID, { title: "Level 3 slab pour", description: "East side poured.", evidence_type: "photo", location: "Level 3" });
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("an edit that is not valid is refused before any request", async () => {
  commit((d) => { d.evidence.push(local()); });
  await expect(updateEvidence(EVIDENCE_ID, { title: "   " })).rejects.toThrow("Title is required");
  await expect(updateEvidence("missing", { title: "x" })).rejects.toThrow("Evidence not found");
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("archive and restore go through the API and are recorded", async () => {
  commit((d) => { d.evidence.push(local()); });

  api({ [`/evidence/${EVIDENCE_ID}`]: record({ archived: true }) });
  await setEvidenceArchived(EVIDENCE_ID, true);
  expect(mocks.apiFetch).toHaveBeenLastCalledWith(`/evidence/${EVIDENCE_ID}`, { method: "PATCH", body: { archived: true } });
  expect(stored()?.archived).toBe(true);
  expect(read.audit(getDb(), PROJECT_ID)[0].action).toBe("evidence.archived");

  api({ [`/evidence/${EVIDENCE_ID}`]: record({ archived: false }) });
  await setEvidenceArchived(EVIDENCE_ID, false);
  expect(stored()?.archived).toBe(false);
  expect(read.audit(getDb(), PROJECT_ID)[0].action).toBe("evidence.restored");
});

test("an API error while archiving leaves the evidence as it was", async () => {
  commit((d) => { d.evidence.push(local()); });
  mocks.apiFetch.mockRejectedValue(new ApiError(404, "Evidence not found", "not_found"));
  await expect(setEvidenceArchived(EVIDENCE_ID, true)).rejects.toThrow("Evidence not found");
  expect(stored()?.archived).toBe(false);
});

test("re-running on failed evidence asks the API to process it again", async () => {
  vi.useFakeTimers();
  commit((d) => { d.evidence.push(local({ processing_status: "failed" })); });
  api({ [`/evidence/${EVIDENCE_ID}/process`]: record({ processing_status: "processing" }), [`/evidence/${EVIDENCE_ID}`]: record() });

  await rerunMatching(EVIDENCE_ID);
  expect(calls(`/evidence/${EVIDENCE_ID}/process`)[0][1]).toEqual({ method: "POST" });
  expect(stored()?.processing_status).toBe("processing");

  await vi.advanceTimersByTimeAsync(1600);
  expect(stored()?.processing_status).toBe("ready");
  expect(read.audit(getDb(), PROJECT_ID).some((a) => a.action === "match.generated")).toBe(true);
});

test("re-running on ready evidence only refreshes the suggestions", async () => {
  commit((d) => { d.evidence.push(local()); });
  await rerunMatching(EVIDENCE_ID);
  expect(mocks.apiFetch).not.toHaveBeenCalled();
  expect(read.audit(getDb(), PROJECT_ID)[0].action).toBe("match.generated");
});

test("with AI switched off, ready evidence gets no suggestions", async () => {
  vi.useFakeTimers();
  setAiAvailable(false);
  api({ [`/projects/${PROJECT_ID}/evidence`]: record({ processing_status: "processing" }), [`/evidence/${EVIDENCE_ID}`]: record() });
  await uploadEvidence(PROJECT_ID, input());
  await vi.advanceTimersByTimeAsync(1600);

  expect(stored()?.processing_status).toBe("ready");
  expect(read.audit(getDb(), PROJECT_ID).some((a) => a.action === "match.generated")).toBe(false);
});

test("a download link is fetched fresh each time and never stored", async () => {
  api({ [`/evidence/${EVIDENCE_ID}`]: { ...record(), download_url: "https://signed.test/original.jpg?token=abc" } });
  await expect(getEvidenceDownloadUrl(EVIDENCE_ID)).resolves.toBe("https://signed.test/original.jpg?token=abc");
  expect(JSON.stringify(getDb())).not.toContain("signed.test");
});

test("a preview that fails to load fetches fresh links, at most once a minute", async () => {
  vi.useFakeTimers();
  api({ [`/projects/${PROJECT_ID}/evidence`]: { items: [record({ preview_url: "https://signed.test/fresh" })] } });

  previewFailed(PROJECT_ID);
  previewFailed(PROJECT_ID);
  await vi.advanceTimersByTimeAsync(10);
  expect(calls(`/projects/${PROJECT_ID}/evidence`)).toHaveLength(1);
  expect(previewOf(stored()!)).toBe("https://signed.test/fresh");

  await vi.advanceTimersByTimeAsync(61_000);
  previewFailed(PROJECT_ID);
  await vi.advanceTimersByTimeAsync(10);
  expect(calls(`/projects/${PROJECT_ID}/evidence`)).toHaveLength(2);
});

test("signing out removes the organisation's evidence from the local copy", () => {
  commit((d) => { d.evidence.push(local()); });
  const elsewhere = getDb().evidence.filter((e) => e.project_id !== PROJECT_ID).length;
  commit(clearCachedProjects);
  expect(stored()).toBeUndefined();
  expect(getDb().evidence).toHaveLength(elsewhere);
});
