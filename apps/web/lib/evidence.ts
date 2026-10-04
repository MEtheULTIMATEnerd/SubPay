// Evidence capture and the evidence library (F06, F07). Components call these
// functions and never talk to the API or the mock directly.
//
// live mode: files and records live behind the FastAPI service. The local
//            store keeps a copy of a project's evidence so pages (and the
//            features still on mock data) can read it at once.
// demo mode: the original prototype behaviour, simulated in lib/api.ts.
//
// Matching evidence to contract items (F08 to F10) is still mock data in both
// modes. In live mode it runs locally once the API reports the evidence ready.
import * as mock from "./api";
import { LIVE } from "./env";
import { ApiError, isApiError } from "./errors";
import { apiFetch } from "./http";
import { commit, getDb } from "./store";
import type { Evidence, EvidenceType } from "./types";

export type EvidenceInput = Omit<mock.EvidenceInput, "file"> & { file: File | null };
export type EvidencePatch = Partial<Pick<Evidence, "title" | "description" | "evidence_type" | "captured_at">> & { location?: string | null };

/** What the API returns: the record plus short-lived signed links. */
type ApiEvidence = Omit<Evidence, "thumbnail"> & { preview_url?: string | null; download_url?: string | null };

const PAGE_SIZE = 200;
const POLL_MS = 1500;
const MAX_POLLS = 120; // about three minutes
const PREVIEW_RETRY_MS = 60_000;

const EXTENSIONS = /\.(jpe?g|png|webp|heic|heif|pdf|docx|xlsx|txt|csv)$/i;
const MIME_TYPES = [
  "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "application/pdf", "text/plain", "text/csv",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
];
export const EVIDENCE_TYPES_MESSAGE =
  "That file type is not supported. Upload a photo (JPEG, PNG, WebP or HEIC), or a PDF, Word, Excel, text or CSV file.";

// ---------- the local copy ----------
// Signed preview links are kept in memory only: they expire, and they must not
// be written to the browser's storage with the rest of the local copy.
const previews = new Map<string, string>();

function toLocal(record: ApiEvidence): Evidence {
  const { preview_url, ...rest } = record;
  delete rest.download_url; // short-lived, fetched fresh when needed
  if (preview_url) previews.set(record.id, preview_url);
  else previews.delete(record.id);
  return { ...rest, thumbnail: null };
}

function storeEvidence(record: ApiEvidence) {
  const evidence = toLocal(record);
  commit((d) => {
    const index = d.evidence.findIndex((e) => e.id === evidence.id);
    if (index === -1) d.evidence.unshift(evidence);
    else d.evidence[index] = evidence;
  });
}

const stored = (id: string) => getDb().evidence.find((e) => e.id === id);

function requireStored(id: string): Evidence {
  const evidence = stored(id);
  if (!evidence) throw new ApiError(404, "Evidence not found", "not_found");
  return evidence;
}

/** The image to show for a record, or null when there is none. */
export function previewOf(evidence: Evidence): string | null {
  return LIVE ? (previews.get(evidence.id) ?? null) : evidence.thumbnail;
}

/** For tests and sign-out: forget every signed preview link and stop following records. */
export function resetEvidenceState() {
  previews.clear();
  previewRefreshedAt.clear();
  watching.clear();
}

// ---------- reading ----------
/** Replace the local copy of this project's evidence with what the API returns. */
export async function refreshEvidence(projectId: string): Promise<void> {
  if (!LIVE) return;
  const records: ApiEvidence[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { items } = await apiFetch<{ items: ApiEvidence[] }>(`/projects/${projectId}/evidence`, { query: { limit: PAGE_SIZE, offset } });
    records.push(...items);
    if (items.length < PAGE_SIZE) break;
  }
  const evidence = records.map(toLocal);
  commit((d) => {
    d.evidence = [...d.evidence.filter((e) => e.project_id !== projectId), ...evidence];
  });
  evidence.filter((e) => e.processing_status === "processing").forEach((e) => watchProcessing(e.id, true));
}

/** A fresh, short-lived link to the stored file. Null for a written note, and in demo mode, where files are not stored. */
export async function getEvidenceDownloadUrl(evidenceId: string): Promise<string | null> {
  if (!LIVE) return null;
  const record = await apiFetch<ApiEvidence>(`/evidence/${evidenceId}`);
  return record.download_url ?? null;
}

const previewRefreshedAt = new Map<string, number>();

/** A preview image failed to load, most likely because its link expired: fetch fresh ones (at most once a minute). */
export function previewFailed(projectId: string) {
  if (!LIVE) return;
  const last = previewRefreshedAt.get(projectId) ?? 0;
  if (Date.now() - last < PREVIEW_RETRY_MS) return;
  previewRefreshedAt.set(projectId, Date.now());
  void refreshEvidence(projectId).catch(() => undefined);
}

// ---------- upload ----------
/**
 * Returns the new record's id. AI processing then runs on its own; the page updates when it finishes.
 * With autoMatch off, no contract-item suggestions are generated (the person is linking it themselves).
 */
export async function uploadEvidence(projectId: string, input: EvidenceInput, { autoMatch = true } = {}): Promise<string> {
  // The same rules in both modes. In live mode the API also checks the file's real contents.
  const { file } = input;
  if (!file && !input.description.trim()) throw new ApiError(422, "Add a file or a written note", "validation_error");
  if (file && file.size > mock.MAX_EVIDENCE_BYTES) throw new ApiError(413, "Evidence files must be 50 MB or smaller", "payload_too_large");
  if (file && !MIME_TYPES.includes(file.type) && !EXTENSIONS.test(file.name)) throw new ApiError(415, EVIDENCE_TYPES_MESSAGE, "unsupported_media_type");
  checkText(input.title, input.description, { titleRequired: false });
  if (!LIVE) return mock.uploadEvidence(projectId, input, { autoMatch });

  const author = getDb().profiles.find((p) => p.id === getDb().session?.profile_id)?.full_name;
  const form = new FormData();
  if (file) form.append("file", file, file.name);
  if (input.title.trim()) form.append("title", input.title.trim());
  form.append("description", input.description.trim());
  form.append("evidence_type", input.evidence_type);
  form.append("captured_at", input.captured_at);
  // uploaded_by, set by the API, is the record of who added it. `author` is only the name to display.
  form.append("metadata", JSON.stringify({ location: input.location, source: input.source ?? "desktop_upload", tags: [], ...(author ? { author } : {}) }));

  const record = await apiFetch<ApiEvidence>(`/projects/${projectId}/evidence`, { method: "POST", form });
  storeEvidence(record);
  mock.logAudit(projectId, "evidence.uploaded", "evidence", record.id, { title: record.title, type: record.evidence_type });
  watchProcessing(record.id, autoMatch);
  return record.id;
}

function checkText(title: string, description: string, { titleRequired }: { titleRequired: boolean }) {
  if (titleRequired && !title.trim()) throw new ApiError(422, "Title is required", "validation_error");
  if (title.trim().length > 200) throw new ApiError(422, "Title must be 200 characters or fewer", "validation_error");
  if (description.trim().length > 5000) throw new ApiError(422, "Description must be 5000 characters or fewer", "validation_error");
}

// ---------- AI processing ----------
const watching = new Set<string>();

/** Follow a record until the API reports it ready or failed, then (optionally) suggest contract items. */
function watchProcessing(evidenceId: string, autoMatch: boolean) {
  if (watching.has(evidenceId)) return;
  watching.add(evidenceId);
  let polls = 0;

  const check = async () => {
    if (!watching.has(evidenceId)) return; // signed out in the meantime
    polls += 1;
    try {
      const record = await apiFetch<ApiEvidence>(`/evidence/${evidenceId}`);
      if (!watching.has(evidenceId)) return;
      if (record.processing_status === "ready" || record.processing_status === "failed") {
        storeEvidence(record);
        watching.delete(evidenceId);
        // Matching is still simulated in the browser (see the note at the top of this file).
        if (record.processing_status === "ready" && autoMatch && getDb().settings.ai_available) mock.runMatching(evidenceId);
        return;
      }
    } catch (err) {
      // Gone, or the session ended: stop. Anything else (a blip) is worth another try.
      if (isApiError(err) && (err.status === 404 || err.status === 401)) {
        watching.delete(evidenceId);
        return;
      }
    }
    if (polls >= MAX_POLLS) {
      watching.delete(evidenceId);
      return;
    }
    setTimeout(() => void check(), POLL_MS);
  };
  setTimeout(() => void check(), POLL_MS);
}

/** "Re-run AI matching": send failed evidence to the AI service again, or refresh the suggestions for ready evidence. */
export async function rerunMatching(evidenceId: string): Promise<void> {
  if (!LIVE) return mock.runMatching(evidenceId);
  const evidence = requireStored(evidenceId);
  if (evidence.processing_status === "ready") return mock.runMatching(evidenceId);
  if (evidence.processing_status !== "processing") {
    storeEvidence(await apiFetch<ApiEvidence>(`/evidence/${evidenceId}/process`, { method: "POST" }));
  }
  watchProcessing(evidenceId, true);
}

// ---------- editing and archiving ----------
/** Save a person's corrections. Only what actually changed is sent; the stored file is never touched. */
export async function updateEvidence(evidenceId: string, patch: EvidencePatch): Promise<void> {
  if (!LIVE) return mock.updateEvidence(evidenceId, patch);
  const current = requireStored(evidenceId);
  checkText(patch.title ?? current.title, patch.description ?? current.description, { titleRequired: true });

  const { location, ...fields } = patch;
  const changes: Record<string, unknown> = {};
  for (const key of Object.keys(fields) as (keyof typeof fields)[]) {
    const value = typeof fields[key] === "string" && key !== "captured_at" ? (fields[key] as string).trim() : fields[key];
    if (value !== undefined && value !== current[key]) changes[key] = value;
  }
  if (location !== undefined && (location ?? null) !== (current.metadata.location ?? null)) {
    // The API replaces the whole metadata object, so send everything that is already there.
    changes.metadata = { ...current.metadata, location };
  }
  if (!Object.keys(changes).length) return;

  storeEvidence(await apiFetch<ApiEvidence>(`/evidence/${evidenceId}`, { method: "PATCH", body: changes }));
  mock.logAudit(current.project_id, "evidence.edited", "evidence", evidenceId, { evidence: current.code, fields: Object.keys(changes) });
}

/** Evidence is never deleted. Archiving hides it from the library; restoring brings it back. */
export async function setEvidenceArchived(evidenceId: string, archived: boolean): Promise<void> {
  if (!LIVE) return mock.setEvidenceArchived(evidenceId, archived);
  const current = requireStored(evidenceId);
  storeEvidence(await apiFetch<ApiEvidence>(`/evidence/${evidenceId}`, { method: "PATCH", body: { archived } }));
  mock.logAudit(current.project_id, archived ? "evidence.archived" : "evidence.restored", "evidence", evidenceId, { evidence: current.code });
}

export type { EvidenceType };
