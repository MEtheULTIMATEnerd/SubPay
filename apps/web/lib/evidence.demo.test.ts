// Demo mode: evidence is simulated in the browser, as in the original prototype.
import { beforeEach, expect, test, vi } from "vitest";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("./env", () => ({ LIVE: false, API_URL: "", SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }));
vi.mock("./http", () => ({ apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("Supabase must not be used in demo mode"); } }));

import { read } from "./api";
import { getEvidenceDownloadUrl, previewFailed, previewOf, refreshEvidence, rerunMatching, setEvidenceArchived, updateEvidence, uploadEvidence } from "./evidence";
import { getDb, resetDb } from "./store";

beforeEach(() => resetDb({ profile_id: "usr-ollie" }));

const find = (id: string) => getDb().evidence.find((e) => e.id === id)!;

test("demo mode uploads, edits, matches and archives locally without calling the API", async () => {
  const file = new File([new Uint8Array(100)], "edge_beams.jpg", { type: "image/jpeg" });
  const id = await uploadEvidence("prj-hume", {
    file, title: "Edge beams", description: "Edge beam formwork level 3", evidence_type: "photo",
    captured_at: "2026-09-14T01:30:00.000Z", location: "Grid C4", thumbnail: "data:image/jpeg;base64,AAAA",
  }, { autoMatch: false });
  await refreshEvidence("prj-hume");

  expect(find(id)).toMatchObject({ title: "Edge beams", processing_status: "ready", metadata: { location: "Grid C4" } });
  expect(previewOf(find(id))).toBe("data:image/jpeg;base64,AAAA"); // the local thumbnail

  await updateEvidence(id, { title: "Edge beams, level 3", location: null });
  expect(find(id)).toMatchObject({ title: "Edge beams, level 3", metadata: { location: null } });

  await rerunMatching(id);
  expect(read.audit(getDb(), "prj-hume").some((a) => a.action === "match.generated" && a.entity_id === id)).toBe(true);

  await setEvidenceArchived(id, true);
  expect(find(id).archived).toBe(true);

  previewFailed("prj-hume");
  await expect(getEvidenceDownloadUrl(id)).resolves.toBeNull(); // demo mode stores no files
  expect(apiFetch).not.toHaveBeenCalled();
});

test("demo mode applies the same upload rules and surfaces them as a rejected promise", async () => {
  const input = { title: "", description: "  ", evidence_type: "message" as const, captured_at: "2026-09-14T01:30:00.000Z", location: null, thumbnail: null };
  const before = getDb().evidence.length;

  await expect(uploadEvidence("prj-hume", { ...input, file: null })).rejects.toThrow("Add a file or a written note");
  const exe = new File(["MZ"], "setup.exe", { type: "application/x-msdownload" });
  await expect(uploadEvidence("prj-hume", { ...input, file: exe })).rejects.toThrow("That file type is not supported");

  expect(getDb().evidence).toHaveLength(before);
});
