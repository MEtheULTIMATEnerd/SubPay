import { read, type Readiness } from "./api";
import { LIVE } from "./env";
import { ApiError } from "./errors";
import type { Db } from "./types";

export const PACKAGE_TITLE = "Draft evidence-support package for human review.";
export const PACKAGE_DISCLAIMER = "Confirmed links record human review decisions; they do not certify completion or contractual compliance, determine legal entitlement, or guarantee payment. This draft is not submitted automatically. Demo exports contain evidence references and metadata, not original source files.";

/** Number each active evidence record once across the claim's confirmed links. */
export function annexure(db: Db, r: Readiness) {
  if (LIVE) throw new ApiError(503, "Live claim packages are not available yet", "service_unavailable");
  const ids = new Set(r.rows.flatMap((row) => row.matches.filter((m) => m.status === "confirmed").map((m) => m.evidence_id)));
  return [...ids].flatMap((id) => {
    const ev = db.evidence.find((e) => e.id === id && e.project_id === r.claim.project_id && !e.archived);
    return ev ? [ev] : [];
  }).map((ev, i) => ({ ref: `A${i + 1}`, ev }));
}

/** Existing structured export, derived from the same readiness snapshot as print. */
export function packageJson(db: Db, r: Readiness) {
  const annex = annexure(db, r);
  const project = read.project(db, r.claim.project_id)!;
  const org = read.org(db);
  const ref = (id: string) => annex.find((a) => a.ev.id === id)?.ref ?? null;
  return {
    title: PACKAGE_TITLE,
    generated_at: new Date().toISOString(),
    disclaimer: PACKAGE_DISCLAIMER,
    project: { id: project.id, name: project.name, client_name: project.client_name },
    organisation: { id: org.id, name: org.name },
    claim: {
      id: r.claim.id, number: r.claim.number, name: r.claim.name,
      period_start: r.claim.period_start, period_end: r.claim.period_end,
      due_date: r.claim.due_date, total_claimed: r.total,
      evidence_support_coverage_pct: r.coverage,
      coverage_basis: "Claimed value of lines with strong confirmed support divided by total claimed value, rounded to a whole percent.",
    },
    items: r.rows.map((row) => ({
      claim_item_id: row.claimItem.id, contract_item_id: row.item.id,
      item_code: row.item.item_code, description: row.item.description,
      source_reference: row.item.source_reference,
      claimed_amount: row.claimItem.claimed_amount,
      claimed_quantity: row.claimItem.claimed_quantity,
      evidence_status: row.state, support_gaps: row.supportGaps,
      evidence: row.matches.filter((m) => m.status === "confirmed" && ref(m.evidence_id)).map((m) => ({
        match_id: m.id, evidence_id: m.evidence_id, annexure_ref: ref(m.evidence_id),
        evidence_code: db.evidence.find((e) => e.id === m.evidence_id)!.code,
        approved_support: true, human_status: m.status, source: m.source,
        confirmed_by: m.confirmed_by ? read.actor(db, m.confirmed_by) : null,
        confirmed_at: m.confirmed_at,
        assessment: m.assessment, missing_evidence: m.missing_evidence,
        ai: m.source === "ai" ? { confidence: m.confidence, assessment: m.assessment, reason: m.reason, missing_evidence: m.missing_evidence } : null,
      })),
      unreviewed_evidence: {
        label: "Unreviewed suggestions - NOT APPROVED SUPPORT",
        approved_support: false,
        suggestions: row.matches.filter((m) => m.status === "suggested").map((m) => ({
          evidence_id: m.evidence_id,
          evidence_code: db.evidence.find((e) => e.id === m.evidence_id)?.code,
          assessment: m.assessment, reason: m.reason, missing_evidence: m.missing_evidence,
        })),
      },
    })),
    annexure: annex.map((a) => ({
      ref: a.ref, evidence_id: a.ev.id, code: a.ev.code, title: a.ev.title,
      type: a.ev.evidence_type, captured_at: a.ev.captured_at,
      location: a.ev.metadata.location, file: a.ev.storage_path,
    })),
    potential_variations: r.variations.map((v) => ({ code: v.code, title: v.title, ai_confidence: v.confidence, reason: v.reason, status: v.status, review_required: v.review_required })),
    notice_flags: r.notices.map((n) => ({ item: n.label, requirement: n.text, due: n.due, certainty: n.definitive ? "identified" : "potential - review contract" })),
  };
}
