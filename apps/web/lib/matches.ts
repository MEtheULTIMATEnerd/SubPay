// Evidence-to-contract-item match confirmation (F10). Components call these
// functions and never talk to the API or the mock directly.
//
// live mode: matches live behind the FastAPI service.
// demo mode: the original prototype behaviour, simulated in lib/api.ts.
import * as mock from "./api";
import { LIVE } from "./env";
import { apiFetch } from "./http";
import { commit } from "./store";
import type { EvidenceMatch } from "./types";

type ApiEvidenceMatch = EvidenceMatch;

// ---------- reading ----------
/** Replace the local copy of this project's matches with what the API returns. */
export async function refreshMatches(projectId: string): Promise<void> {
  if (!LIVE) return;
  const { items } = await apiFetch<{ items: ApiEvidenceMatch[] }>(`/projects/${projectId}/evidence-matches`);
  commit((d) => {
    d.evidence_matches = [...d.evidence_matches.filter((m) => {
      const ev = d.evidence.find((e) => e.id === m.evidence_id);
      return ev && ev.project_id !== projectId;
    }), ...items];
  });
}

// ---------- actions ----------
/** Confirm an AI-suggested match. */
export async function confirmMatch(projectId: string, id: string): Promise<void> {
  if (!LIVE) return mock.reviewMatch(id, "confirmed");
  const match = await apiFetch<ApiEvidenceMatch>(`/projects/${projectId}/evidence-matches/${id}/confirm`, { method: "POST" });
  commit((d) => {
    const m = d.evidence_matches.find((x) => x.id === id);
    if (m) Object.assign(m, match);
  });
}

/** Reject an AI-suggested match. */
export async function rejectMatch(projectId: string, id: string): Promise<void> {
  if (!LIVE) return mock.reviewMatch(id, "rejected");
  const match = await apiFetch<ApiEvidenceMatch>(`/projects/${projectId}/evidence-matches/${id}/reject`, { method: "POST" });
  commit((d) => {
    const m = d.evidence_matches.find((x) => x.id === id);
    if (m) Object.assign(m, match);
  });
}

/** Reopen a confirmed/rejected match back to suggested. */
export async function reopenMatch(projectId: string, id: string): Promise<void> {
  if (!LIVE) return mock.reviewMatch(id, "suggested");
  const match = await apiFetch<ApiEvidenceMatch>(`/projects/${projectId}/evidence-matches/${id}/reopen`, { method: "POST" });
  commit((d) => {
    const m = d.evidence_matches.find((x) => x.id === id);
    if (m) Object.assign(m, match);
  });
}

/** Link evidence to a contract item (human-confirmed). */
export async function linkEvidence(projectId: string, evidenceId: string, contractItemId: string, replacesMatchId?: string): Promise<void> {
  if (!LIVE) return mock.linkEvidence(evidenceId, contractItemId, replacesMatchId);
  const match = await apiFetch<ApiEvidenceMatch>(`/projects/${projectId}/evidence/${evidenceId}/link/${contractItemId}`, { method: "POST" });
  commit((d) => {
    if (replacesMatchId) {
      const old = d.evidence_matches.find((m) => m.id === replacesMatchId);
      if (old) Object.assign(old, { status: "rejected", confirmed_by: d.session?.profile_id ?? null, confirmed_at: new Date().toISOString(), updated_at: new Date().toISOString() });
    }
    d.evidence_matches.push(match);
  });
}
