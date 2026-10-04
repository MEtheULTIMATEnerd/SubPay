// Mock service layer. Each function maps to an agreed /api/v1 endpoint (see
// docs/api-contracts.md). Identity and organisation are always derived from the
// session, never from arguments — same rule the FastAPI layer must follow.
// ponytail: synchronous localStorage calls; make these fetch() wrappers when FastAPI lands.
import { commit, getDb, resetDb } from "./store";
import * as ai from "./ai";
import { ApiError } from "./errors";
import type {
  Db, Profile, Project, ContractItem, Evidence, EvidenceMatch, Claim, Completeness, EvidenceType,
} from "./types";

export { ApiError };

const now = () => new Date().toISOString();
const uid = () => crypto.randomUUID();
const PROCESSING_MS = 1500;

// ---------- guards (the RLS equivalent) ----------
function me(d: Db): Profile {
  const p = d.session && d.profiles.find((x) => x.id === d.session!.profile_id);
  if (!p) throw new ApiError(401, "Not signed in");
  return p;
}
function project(d: Db, id: string): Project {
  const p = d.projects.find((x) => x.id === id);
  if (!p || p.organisation_id !== me(d).organisation_id) throw new ApiError(404, "Project not found");
  return p;
}
const contract = (d: Db, id: string) => {
  const c = d.contracts.find((x) => x.id === id);
  if (!c) throw new ApiError(404, "Contract not found");
  project(d, c.project_id);
  return c;
};
const contractItem = (d: Db, id: string) => {
  const i = d.contract_items.find((x) => x.id === id);
  if (!i) throw new ApiError(404, "Contract item not found");
  return { item: i, contract: contract(d, i.contract_id) };
};
const evidence = (d: Db, id: string) => {
  const e = d.evidence.find((x) => x.id === id);
  if (!e) throw new ApiError(404, "Evidence not found");
  project(d, e.project_id);
  return e;
};
const match = (d: Db, id: string) => {
  const m = d.evidence_matches.find((x) => x.id === id);
  if (!m) throw new ApiError(404, "Match not found");
  evidence(d, m.evidence_id);
  return m;
};
const claim = (d: Db, id: string) => {
  const c = d.claims.find((x) => x.id === id);
  if (!c) throw new ApiError(404, "Claim not found");
  project(d, c.project_id);
  return c;
};

function audit(d: Db, project_id: string | null, action: string, entity: string, entity_id: string, metadata: Record<string, unknown> = {}, ai = false) {
  d.audit_events.unshift({
    id: uid(), organisation_id: me(d).organisation_id, project_id, actor_id: ai ? null : me(d).id,
    action, entity, entity_id, metadata, created_at: now(),
  });
}
function notify(d: Db, project_id: string, title: string, body: string, href: string) {
  for (const p of d.profiles.filter((x) => x.organisation_id === me(d).organisation_id))
    d.notifications.unshift({ id: uid(), profile_id: p.id, project_id, title, body, href, status: "unread", created_at: now() });
}

// ---------- read helpers (pure, take a Db snapshot from useDb) ----------
export const read = {
  me: (d: Db) => (d.session ? d.profiles.find((x) => x.id === d.session!.profile_id) ?? null : null),
  org: (d: Db) => d.organisations.find((o) => o.id === me(d).organisation_id)!,
  projects: (d: Db) => d.projects.filter((p) => p.organisation_id === me(d).organisation_id),
  project: (d: Db, id: string) => { try { return project(d, id); } catch { return null; } },
  contracts: (d: Db, pid: string) => (project(d, pid), d.contracts.filter((c) => c.project_id === pid)),
  contract: (d: Db, id: string) => { try { return contract(d, id); } catch { return null; } },
  contractItems: (d: Db, cid: string) => (contract(d, cid), d.contract_items.filter((i) => i.contract_id === cid)),
  projectItems: (d: Db, pid: string) => {
    const cids = new Set(read.contracts(d, pid).map((c) => c.id));
    return d.contract_items.filter((i) => cids.has(i.contract_id));
  },
  evidence: (d: Db, pid: string) => (project(d, pid), d.evidence.filter((e) => e.project_id === pid)),
  matches: (d: Db, pid: string) => {
    const ids = new Set(read.evidence(d, pid).map((e) => e.id));
    return d.evidence_matches.filter((m) => ids.has(m.evidence_id));
  },
  claims: (d: Db, pid: string) => (project(d, pid), d.claims.filter((c) => c.project_id === pid)),
  claim: (d: Db, id: string) => { try { return claim(d, id); } catch { return null; } },
  variations: (d: Db, pid: string) => (project(d, pid), d.variations.filter((v) => v.project_id === pid)),
  audit: (d: Db, pid: string) => (project(d, pid), d.audit_events.filter((a) => a.project_id === pid)),
  notifications: (d: Db) => d.notifications.filter((n) => n.profile_id === me(d).id && n.status !== "dismissed"),
  actor: (d: Db, id: string | null) => (id ? d.profiles.find((p) => p.id === id)?.full_name ?? "Unknown" : "SubPay AI"),
};

// ---------- F12 readiness (uses completeness of human-confirmed matches) ----------
export function completeness(matches: EvidenceMatch[]): Completeness {
  const live = matches.filter((m) => m.status !== "rejected");
  const confirmed = live.filter((m) => m.status === "confirmed");
  if (!live.length) return "missing";
  if (!confirmed.length) return "weak"; // only unconfirmed AI suggestions
  return confirmed.some((m) => m.assessment === "strong" && !m.missing_evidence.length) ? "strong" : "partial";
}

export function readiness(d: Db, claimId: string) {
  const c = claim(d, claimId);
  const items = read.projectItems(d, c.project_id);
  const matches = read.matches(d, c.project_id);
  const rows = d.claim_items
    .filter((ci) => ci.claim_id === claimId)
    .map((ci) => {
      const item = items.find((i) => i.id === ci.contract_item_id)!;
      const m = matches.filter((x) => x.contract_item_id === item.id);
      return {
        claimItem: ci,
        item,
        matches: m,
        state: completeness(m),
        pending: m.filter((x) => x.status === "suggested").length,
        reviewed: m.some((x) => x.status === "confirmed") && !m.some((x) => x.status === "suggested"),
      };
    })
    .sort((a, b) => a.item.item_code.localeCompare(b.item.item_code, undefined, { numeric: true }));

  const sum = (r: typeof rows) => r.reduce((s, x) => s + x.claimItem.claimed_amount, 0);
  const by = (s: Completeness) => rows.filter((r) => r.state === s);
  const total = sum(rows);
  const variations = read.variations(d, c.project_id).filter((v) => v.status !== "dismissed");
  const today = new Date(new Date().toDateString()).getTime();
  const daysLeft = (iso: string) => Math.round((new Date(`${iso}T00:00`).getTime() - today) / 86_400_000);
  const notices = [
    ...rows.filter((r) => r.item.notice_requirement).map((r) => ({
      key: r.item.id, label: `${r.item.item_code} ${r.item.description}`, text: r.item.notice_requirement!,
      due: r.item.due_date, days: r.item.due_date ? daysLeft(r.item.due_date) : null,
      // uncertain extraction or unreviewed line => never presented as definitive
      definitive: r.item.review_status === "confirmed" && (r.item.extraction_confidence ?? 0) >= 0.85,
    })),
    ...variations.filter((v) => v.notice_due).map((v) => ({
      key: v.id, label: `${v.code} ${v.title}`, text: "Variation notice requirement identified",
      due: v.notice_due, days: daysLeft(v.notice_due!), definitive: false,
    })),
  ].sort((a, b) => (a.days ?? 999) - (b.days ?? 999));

  return {
    claim: c,
    rows,
    total,
    counts: { strong: by("strong").length, partial: by("partial").length, weak: by("weak").length, missing: by("missing").length },
    values: { strong: sum(by("strong")), partial: sum(by("partial")), weak: sum(by("weak")), missing: sum(by("missing")) },
    /** Evidence support coverage — share of claimed value with strong, human-confirmed evidence. Not a validity score. */
    coverage: total ? Math.round((sum(by("strong")) / total) * 100) : 0,
    reviewed: rows.filter((r) => r.reviewed).length,
    pendingMatches: rows.reduce((s, r) => s + r.pending, 0),
    variations,
    notices,
  };
}
export type Readiness = ReturnType<typeof readiness>;

// ---------- F01 auth ----------
// Demo mode only. With Supabase configured, lib/auth.ts uses Supabase Auth and
// GET/PATCH /api/v1/me instead. UI code should import from lib/auth.ts.
export function signIn(email: string, password: string) {
  const p = getDb().profiles.find((x) => x.email.toLowerCase() === email.trim().toLowerCase());
  // ponytail: demo accepts any non-empty password; Supabase Auth owns credentials for real.
  if (!p || !password) throw new ApiError(401, "Email or password is incorrect");
  commit((d) => { d.session = { profile_id: p.id }; });
}
export function signUp(input: { full_name: string; email: string; password: string; organisation: string }) {
  if (input.password.length < 8) throw new ApiError(422, "Password must be at least 8 characters");
  if (getDb().profiles.some((p) => p.email.toLowerCase() === input.email.trim().toLowerCase()))
    throw new ApiError(409, "An account with this email already exists");
  commit((d) => {
    const org = { id: uid(), name: input.organisation.trim(), created_at: now(), updated_at: now() };
    const prof: Profile = { id: uid(), email: input.email.trim(), organisation_id: org.id, full_name: input.full_name.trim(), role: "owner", created_at: now(), updated_at: now() };
    d.organisations.push(org);
    d.profiles.push(prof);
    d.session = { profile_id: prof.id };
  });
}
export const signOut = () => commit((d) => { d.session = null; });
export function updateProfile(full_name: string) {
  commit((d) => { const p = me(d); p.full_name = full_name.trim(); p.updated_at = now(); });
}
export const resetDemo = () => resetDb(getDb().session);
export const setAiAvailable = (v: boolean) => commit((d) => { d.settings.ai_available = v; });

// ---------- F02 projects ----------
type ProjectInput = Pick<Project, "name" | "client_name" | "site_address" | "start_date" | "end_date">;
function validateProject(p: ProjectInput) {
  if (!p.name.trim()) throw new ApiError(422, "Project name is required");
  if (p.start_date && p.end_date && p.end_date < p.start_date) throw new ApiError(422, "End date must be after start date");
}
export function createProject(input: ProjectInput): string {
  validateProject(input);
  const id = uid();
  commit((d) => {
    const u = me(d);
    d.projects.push({ ...input, id, organisation_id: u.organisation_id, status: "active", created_by: u.id, created_at: now(), updated_at: now() });
    audit(d, id, "project.created", "project", id, { name: input.name });
  });
  return id;
}
export function updateProject(id: string, patch: ProjectInput) {
  validateProject(patch);
  commit((d) => { Object.assign(project(d, id), patch, { updated_at: now() }); audit(d, id, "project.updated", "project", id); });
}
export function setProjectStatus(id: string, status: Project["status"]) {
  commit((d) => { Object.assign(project(d, id), { status, updated_at: now() }); audit(d, id, `project.${status === "archived" ? "archived" : "restored"}`, "project", id); });
}

// ---------- F03/F04 contracts ----------
export const CONTRACT_TYPES = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"];
export const MAX_CONTRACT_BYTES = 25 * 1024 * 1024;

export function uploadContract(pid: string, file: { name: string; type: string; size: number }): string {
  const okType = CONTRACT_TYPES.includes(file.type) || /\.(pdf|docx)$/i.test(file.name);
  if (!okType) throw new ApiError(415, "Only PDF or DOCX contracts are supported");
  if (file.size > MAX_CONTRACT_BYTES) throw new ApiError(413, "Contract must be 25 MB or smaller");
  const id = uid();
  commit((d) => {
    project(d, pid);
    const ext = file.name.split(".").pop()!.toLowerCase();
    d.contracts.push({
      id, project_id: pid, original_filename: file.name, storage_path: `contracts/${pid}/${id}/original.${ext}`,
      mime_type: file.type || (ext === "pdf" ? CONTRACT_TYPES[0] : CONTRACT_TYPES[1]), size_bytes: file.size, page_count: null,
      processing_status: "uploaded", error: null, uploaded_by: me(d).id, created_at: now(), updated_at: now(), processed_at: null,
    });
    audit(d, pid, "contract.uploaded", "contract", id, { filename: file.name });
  });
  startExtraction(id);
  return id;
}

export function startExtraction(id: string) {
  commit((d) => { Object.assign(contract(d, id), { processing_status: "processing", error: null, updated_at: now() }); });
  setTimeout(() => runExtraction(id), PROCESSING_MS);
}

export function runExtraction(id: string) {
  commit((d) => {
    const c = contract(d, id);
    if (!d.settings.ai_available) {
      Object.assign(c, { processing_status: "failed", error: new ai.AiUnavailableError().message, updated_at: now() });
      return;
    }
    const result = ai.extractContract(c.id, c.original_filename);
    d.contract_items = d.contract_items.filter((i) => i.contract_id !== id);
    for (const x of result.items) {
      d.contract_items.push({
        id: uid(), contract_id: id, item_code: x.item_code, description: x.description, quantity: x.quantity, unit: x.unit,
        rate: x.rate, amount: x.amount, conditions: x.conditions, notice_requirement: x.notice_requirement, due_date: x.due_date,
        extraction_confidence: x.confidence, review_status: "draft", edited_by_human: false, reviewed_by: null,
        source_reference: x.source_reference, created_at: now(), updated_at: now(),
      });
    }
    Object.assign(c, { processing_status: "ready", processed_at: now(), updated_at: now() });
    audit(d, c.project_id, "contract.extracted", "contract", id, { items: result.items.length }, true);
    notify(d, c.project_id, "Claim schedule ready for review", `${result.items.length} items extracted from ${c.original_filename}.`, `/projects/${c.project_id}/contracts/${id}/items`);
  });
}

type ItemPatch = Partial<Pick<ContractItem, "description" | "quantity" | "unit" | "rate" | "amount" | "conditions" | "notice_requirement" | "due_date">>;
export function updateContractItem(id: string, patch: ItemPatch) {
  commit((d) => {
    const { item, contract: c } = contractItem(d, id);
    const changed = Object.keys(patch).filter((k) => patch[k as keyof ItemPatch] !== item[k as keyof ItemPatch]);
    if (!changed.length) return;
    // previous values kept in the audit log so AI output is never silently overwritten
    audit(d, c.project_id, "contract_item.edited", "contract_item", id, {
      item: item.item_code, fields: changed, before: Object.fromEntries(changed.map((k) => [k, item[k as keyof ItemPatch]])),
    });
    Object.assign(item, patch, { edited_by_human: true, updated_at: now() });
  });
}
export function reviewContractItem(id: string, status: "confirmed" | "rejected" | "draft") {
  commit((d) => {
    const { item, contract: c } = contractItem(d, id);
    Object.assign(item, { review_status: status, reviewed_by: status === "draft" ? null : me(d).id, updated_at: now() });
    audit(d, c.project_id, `contract_item.${status}`, "contract_item", id, { item: item.item_code });
  });
}

// ---------- F06/F07 evidence ----------
export interface EvidenceInput {
  file: { name: string; type: string; size: number } | null;
  title: string;
  description: string;
  evidence_type: EvidenceType;
  captured_at: string;
  location: string | null;
  thumbnail: string | null;
  source?: string;
}
export const MAX_EVIDENCE_BYTES = 50 * 1024 * 1024;

export function uploadEvidence(pid: string, input: EvidenceInput, { autoMatch = true } = {}): string {
  if (input.file && input.file.size > MAX_EVIDENCE_BYTES) throw new ApiError(413, "Evidence files must be 50 MB or smaller");
  if (!input.file && !input.description.trim()) throw new ApiError(422, "Add a file or a written note");
  const id = uid();
  commit((d) => {
    project(d, pid);
    const n = d.evidence.filter((e) => e.project_id === pid).length + 1;
    const ext = input.file?.name.split(".").pop() ?? "txt";
    d.evidence.push({
      id, code: `EV-${String(n).padStart(3, "0")}`, project_id: pid, uploaded_by: me(d).id,
      storage_path: `evidence/${pid}/${id}/original.${ext}`, original_filename: input.file?.name ?? "note.txt",
      mime_type: input.file?.type || "text/plain", evidence_type: input.evidence_type, captured_at: input.captured_at,
      title: input.title.trim() || input.file?.name || "Note", description: input.description.trim(),
      metadata: { location: input.location, source: input.source ?? "desktop_upload", tags: [], author: me(d).full_name },
      thumbnail: input.thumbnail, processing_status: autoMatch ? "processing" : "ready", archived: false, created_at: now(), updated_at: now(),
    });
    audit(d, pid, "evidence.uploaded", "evidence", id, { title: input.title, type: input.evidence_type });
  });
  if (autoMatch) setTimeout(() => runMatching(id), PROCESSING_MS);
  return id;
}

/** F08/F09/F16 — run (mock) AI understanding + matching + variation detection on one evidence record. */
export function runMatching(id: string) {
  commit((d) => {
    const ev = evidence(d, id);
    if (!d.settings.ai_available) {
      Object.assign(ev, { processing_status: "failed", updated_at: now() });
      return;
    }
    const items = read.projectItems(d, ev.project_id).filter((i) => i.review_status === "confirmed");
    const result = ai.matchEvidence(ev, items);
    d.evidence_matches = d.evidence_matches.filter((m) => !(m.evidence_id === id && m.status === "suggested"));
    for (const s of result.matches) {
      if (d.evidence_matches.some((m) => m.evidence_id === id && m.contract_item_id === s.contract_item_id)) continue;
      d.evidence_matches.push({
        id: uid(), evidence_id: id, ...s, status: "suggested", source: "ai",
        confirmed_by: null, confirmed_at: null, created_at: now(), updated_at: now(),
      });
    }
    Object.assign(ev, { processing_status: "ready", updated_at: now() });
    audit(d, ev.project_id, "match.generated", "evidence", id, { evidence: ev.code, count: result.matches.length }, true);
    if (result.matches.length)
      notify(d, ev.project_id, "AI match requires confirmation", `${ev.title} has ${result.matches.length} suggested contract match${result.matches.length > 1 ? "es" : ""}.`, `/projects/${ev.project_id}/review?evidence=${id}`);

    const flag = ai.detectVariation(ev, result);
    if (flag) {
      const vid = uid();
      const code = `VAR-${String(d.variations.filter((v) => v.project_id === ev.project_id).length + 1).padStart(2, "0")}`;
      d.variations.push({
        id: vid, project_id: ev.project_id, code, title: ev.title, potential_variation: true, confidence: flag.confidence, reason: flag.reason,
        estimated_amount: null, related_evidence_ids: flag.related_evidence_ids, related_contract_item_id: null,
        notice_due: null, review_required: true, status: "flagged", created_at: now(),
      });
      audit(d, ev.project_id, "variation.flagged", "variation", vid, { code, evidence: ev.code }, true);
      notify(d, ev.project_id, "Potential variation detected", `${ev.title} may describe work outside the contract. Review required.`, `/projects/${ev.project_id}/evidence`);
    }
  });
}

export function updateEvidence(id: string, patch: Partial<Pick<Evidence, "title" | "description" | "evidence_type" | "captured_at">> & { location?: string | null }) {
  commit((d) => {
    const ev = evidence(d, id);
    const { location, ...rest } = patch;
    Object.assign(ev, rest, { updated_at: now() });
    if (location !== undefined) ev.metadata = { ...ev.metadata, location };
    audit(d, ev.project_id, "evidence.edited", "evidence", id, { evidence: ev.code });
  });
}
export function setEvidenceArchived(id: string, archived: boolean) {
  commit((d) => {
    const ev = evidence(d, id);
    ev.archived = archived;
    audit(d, ev.project_id, archived ? "evidence.archived" : "evidence.restored", "evidence", id, { evidence: ev.code });
  });
}

// ---------- F10 human match confirmation ----------
export function reviewMatch(id: string, status: "confirmed" | "rejected" | "suggested") {
  commit((d) => {
    const m = match(d, id);
    const ev = evidence(d, m.evidence_id);
    const { item } = contractItem(d, m.contract_item_id);
    Object.assign(m, { status, confirmed_by: status === "suggested" ? null : me(d).id, confirmed_at: status === "suggested" ? null : now(), updated_at: now() });
    audit(d, ev.project_id, status === "suggested" ? "match.reopened" : `match.${status}`, "evidence_match", id, { evidence: ev.code, item: item.item_code });
  });
}
/** Human links evidence to a contract item (new link or change of match). Always human-confirmed. */
export function linkEvidence(evidenceId: string, contractItemId: string, replacesMatchId?: string) {
  commit((d) => {
    const ev = evidence(d, evidenceId);
    const { item } = contractItem(d, contractItemId);
    if (replacesMatchId) Object.assign(match(d, replacesMatchId), { status: "rejected", confirmed_by: me(d).id, confirmed_at: now(), updated_at: now() });
    const existing = d.evidence_matches.find((m) => m.evidence_id === evidenceId && m.contract_item_id === contractItemId);
    if (existing) Object.assign(existing, { status: "confirmed", confirmed_by: me(d).id, confirmed_at: now(), updated_at: now() });
    else d.evidence_matches.push({
      id: uid(), evidence_id: evidenceId, contract_item_id: contractItemId, confidence: 1, assessment: "strong",
      reason: "Linked manually by a person.", missing_evidence: [], status: "confirmed", source: "human",
      confirmed_by: me(d).id, confirmed_at: now(), created_at: now(), updated_at: now(),
    });
    audit(d, ev.project_id, replacesMatchId ? "match.edited" : "match.linked", "evidence_match", evidenceId, { evidence: ev.code, item: item.item_code });
  });
}

// ---------- F12–F16 claims & variations ----------
export function createClaim(pid: string): string {
  const id = uid();
  commit((d) => {
    project(d, pid);
    const items = read.projectItems(d, pid).filter((i) => i.review_status === "confirmed");
    if (!items.length) throw new ApiError(422, "Confirm at least one contract item before creating a claim");
    const number = Math.max(0, ...d.claims.filter((c) => c.project_id === pid).map((c) => c.number)) + 1;
    const t = new Date();
    const iso = (x: Date) => x.toLocaleDateString("en-CA");
    d.claims.push({
      id, project_id: pid, number, name: `Claim #${number}, ${t.toLocaleString("en-AU", { month: "long", year: "numeric" })}`,
      period_start: iso(new Date(t.getFullYear(), t.getMonth(), 1)), period_end: iso(new Date(t.getFullYear(), t.getMonth() + 1, 0)),
      due_date: iso(new Date(t.getFullYear(), t.getMonth() + 1, 0)), status: "draft", created_by: me(d).id, created_at: now(), updated_at: now(),
    });
    for (const i of items)
      d.claim_items.push({ id: uid(), claim_id: id, contract_item_id: i.id, claimed_quantity: i.quantity, claimed_amount: i.amount ?? 0, created_at: now(), updated_at: now() });
    audit(d, pid, "claim.created", "claim", id, { number });
  });
  return id;
}
export function recordExport(claimId: string, format: "pdf" | "json") {
  commit((d) => {
    const c: Claim = claim(d, claimId);
    c.status = "exported";
    audit(d, c.project_id, "package.exported", "claim", claimId, { format, claim: c.name });
  });
}
export function setVariationStatus(id: string, status: "acknowledged" | "dismissed" | "flagged") {
  commit((d) => {
    const v = d.variations.find((x) => x.id === id);
    if (!v) throw new ApiError(404, "Variation not found");
    project(d, v.project_id);
    v.status = status;
    audit(d, v.project_id, `variation.${status}`, "variation", id, { code: v.code });
  });
}

// ---------- F18 notifications ----------
export function setNotification(id: string, status: "read" | "dismissed" | "unread") {
  commit((d) => {
    const n = d.notifications.find((x) => x.id === id && x.profile_id === me(d).id);
    if (n) n.status = status;
  });
}
export const markAllRead = () =>
  commit((d) => { for (const n of d.notifications) if (n.profile_id === me(d).id && n.status === "unread") n.status = "read"; });

