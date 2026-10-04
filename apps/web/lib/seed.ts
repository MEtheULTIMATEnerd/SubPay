// Deterministic demo data (F20). Fictional project — no real contract documents.
// Dates are relative to "now" so deadlines in the demo are always upcoming.
import type { Db, ContractItem, Evidence, EvidenceMatch, ClaimItem } from "./types";

const DAY = 86_400_000;
export const SEED_VERSION = 4;

export function seed(now = Date.now()): Db {
  const at = (days: number, h = 9, m = 0) => {
    const d = new Date(now + days * DAY);
    d.setHours(h, m, 0, 0);
    return d.toISOString();
  };
  const date = (days: number) => new Date(now + days * DAY).toLocaleDateString("en-CA"); // local YYYY-MM-DD
  const t = at(-30);

  const ORG = "org-kearney";
  const ME = "usr-ollie";
  const P = "prj-hume";
  const C = "con-hume";

  const items: [string, string, string, number | null, string, number, number, number, Partial<ContractItem>?][] = [
    // code, description, clause, qty, unit, rate, amount, confidence, extra
    ["14.2", "Formwork, edge beams L3", "12.4", 230, "m²", 80, 18400, 0.96],
    ["14.3", "Formwork, columns L3", "12.4", 142, "m²", 100, 14200, 0.94],
    ["14.4", "Formwork, slab soffit L3", "12.4", 760, "m²", 30, 22800, 0.95],
    ["14.5", "Concrete supply, L3 slab", "12.9", 165, "m³", 250, 41250, 0.91,
      { notice_requirement: "Notify builder 48 hours before each pour", due_date: date(12) }],
    ["14.6", "Formwork strip and clean", "12.4", 640, "m²", 8, 5120, 0.93],
    ["15.1", "Reinforcement fixing, L3 slab", "12.6", 22, "t", 750, 16500, 0.92],
    ["17.1", "Site establishment", "9.1", 1, "item", 6800, 6800, 0.74,
      { review_status: "draft", conditions: "Payable in two equal instalments (wording ambiguous)" }],
    ["18.2", "Edge protection and screens", "9.4", 1, "item", 7400, 7400, 0.88],
    ["19.1", "Post-tension stressing, L3", "12.11", 1, "item", 8900, 8900, 0.9],
    ["21.4", "Concrete pump hire, L3", "14.1", 4, "day", 800, 3200, 0.87],
    ["22.3", "Crane hire, standing time", "14.2", 32, "hr", 300, 9600, 0.58,
      { review_status: "draft", notice_requirement: "Written site instruction required within 5 business days of standing time", due_date: date(6),
        conditions: "Standing time is worded unusually in this contract" }],
    ["31.0", "Provisional sum, penetrations", "6.3", null, "", 0, 12000, 0.89,
      { notice_requirement: "Notify builder before expending provisional sum", due_date: date(20) }],
  ];

  const contract_items: ContractItem[] = items.map(([code, desc, clause, qty, unit, rate, amount, conf, extra], i) => ({
    id: `ci-${i + 1}`,
    contract_id: C,
    item_code: code,
    description: desc,
    quantity: qty ?? null,
    unit: unit || null,
    rate: rate || null,
    amount,
    conditions: null,
    notice_requirement: null,
    due_date: null,
    extraction_confidence: conf,
    review_status: "confirmed",
    edited_by_human: false,
    reviewed_by: ME,
    source_reference: `Clause ${clause} · Schedule of rates, item ${code.split(".")[0]}`,
    created_at: t,
    updated_at: t,
    ...extra,
    ...(extra?.review_status === "draft" ? { reviewed_by: null } : {}),
  }));
  const ci = (code: string) => contract_items.find((x) => x.item_code === code)!.id;

  const ev: [string, Evidence["evidence_type"], string, string, string | null, number, number, number][] = [
    // title, type, description, source/author, location, day offset, hour, minute
    ["Site photo", "photo", "Edge beam formwork installed, grid C4 level 3", "Ollie R.", "Grid C4, Level 3", -12, 15, 12],
    ["Site photo", "photo", "Edge beam formwork L3 east side, ready for pour", "Ollie R.", "Grid C4, Level 3", -12, 16, 40],
    ["Site instruction email", "message", "Site engineer confirms edge beam formwork L3 complete and inspected", "Forwarded from the site engineer", null, -11, 8, 5],
    ["Delivery docket #4471", "docket", "Formwork ply and timber delivered for edge beams", "Scanned on site · text read automatically", null, -16, 7, 30],
    ["Concrete pour docket #8812", "docket", "Concrete supply 92 m3 L3 slab pour, 32MPa", "Scanned on site", "Level 3", -9, 11, 0],
    ["Site photo", "photo", "L3 slab concrete pour in progress", "Ollie R.", "Level 3", -9, 10, 20],
    ["Crane timesheet", "document", "Crane standing time 14 hrs waiting on builder access", "Uploaded by office", null, -7, 17, 0],
    ["Site photo", "photo", "Latent slab condition at grid B2, additional propping and extra formwork required", "Ollie R.", "Grid B2, Level 3", -5, 9, 45],
    ["Site photo", "photo", "Formwork strip and clean L2 complete", "Jas M.", "Level 2", -14, 14, 0],
    ["Text from builder's foreman", "message", "Additional drainage penetrations requested through L3 slab, not on drawings", "SMS from Bellrock foreman", null, -6, 12, 30],
    ["Site photo", "photo", "Column formwork L3 grid C1–C6", "Ollie R.", "Level 3", -15, 13, 10],
    ["Reinforcement delivery docket #5530", "docket", "Reinforcement mesh and bar delivered, 22 t, L3 slab", "Scanned on site", null, -13, 7, 0],
    ["Post-tension stressing record", "document", "Post-tension stressing record L3, all tendons stressed", "Uploaded by office", null, -8, 15, 0],
    ["Site photo", "photo", "Edge protection and screens installed L3 to L4", "Jas M.", "Level 3", -10, 8, 15],
    ["Site establishment invoice", "document", "Site sheds, amenities and hoarding for site establishment", "Uploaded by office", null, -28, 10, 0],
  ];

  const evidence: Evidence[] = ev.map(([title, type, description, author, location, d, h, m], i) => {
    const id = `ev-${i + 1}`;
    const ext = type === "photo" ? "jpg" : "pdf";
    return {
      id,
      code: `EV-${String(i + 1).padStart(3, "0")}`,
      project_id: P,
      uploaded_by: ME,
      storage_path: `evidence/${P}/${id}/original.${ext}`,
      original_filename: `${title.toLowerCase().replace(/[^a-z0-9]+/g, "_")}_${i + 1}.${ext}`,
      mime_type: type === "photo" ? "image/jpeg" : "application/pdf",
      evidence_type: type,
      captured_at: at(d, h, m),
      title,
      description,
      metadata: { location, source: type === "photo" ? "mobile_upload" : "desktop_upload", tags: [], author },
      thumbnail: null,
      processing_status: "ready",
      archived: false,
      created_at: at(d, h, m),
      updated_at: at(d, h, m),
    };
  });

  const m = (
    n: number, evId: string, code: string, confidence: number, assessment: EvidenceMatch["assessment"],
    reason: string, missing: string[], status: EvidenceMatch["status"],
  ): EvidenceMatch => ({
    id: `em-${n}`,
    evidence_id: evId,
    contract_item_id: ci(code),
    confidence,
    assessment,
    reason,
    missing_evidence: missing,
    status,
    source: "ai",
    confirmed_by: status === "suggested" ? null : ME,
    confirmed_at: status === "suggested" ? null : at(-4),
    created_at: at(-10),
    updated_at: at(-4),
  });
  const evidence_matches: EvidenceMatch[] = [
    m(1, "ev-1", "14.2", 0.96, "strong", "Photo shows edge beam formwork at grid C4, level 3, matching item 14.2.", [], "confirmed"),
    m(2, "ev-2", "14.2", 0.94, "strong", "Photo shows edge beam formwork on level 3, east side.", [], "confirmed"),
    m(3, "ev-3", "14.2", 0.88, "strong", "Site engineer's email references completed edge beam formwork on L3.", [], "confirmed"),
    m(4, "ev-4", "14.2", 0.61, "weak", "Docket lists formwork materials but the delivery date is earlier than the claim period.", ["date confirmation"], "suggested"),
    m(5, "ev-5", "14.5", 0.93, "strong", "Pour docket records 92 m³ concrete supplied to the L3 slab.", ["remaining 73 m³ quantity support"], "confirmed"),
    m(6, "ev-6", "14.5", 0.86, "partial", "Photo shows an L3 slab pour; quantity not visible.", ["quantity confirmation"], "suggested"),
    m(7, "ev-7", "22.3", 0.58, "weak", "Timesheet records standing time, but no written instruction from the builder is linked.", ["written site instruction"], "suggested"),
    m(8, "ev-9", "14.6", 0.9, "strong", "Photo shows stripped and cleaned formwork; note it is level 2, not level 3.", ["level 3 strip evidence"], "confirmed"),
    m(9, "ev-11", "14.3", 0.92, "strong", "Photo shows column formwork on L3 grid C1–C6.", [], "confirmed"),
    m(10, "ev-12", "15.1", 0.9, "strong", "Docket records 22 t reinforcement delivered for the L3 slab.", [], "confirmed"),
    m(11, "ev-10", "31.0", 0.66, "partial", "Message requests penetrations that may fall under the provisional sum.", ["builder approval to expend provisional sum"], "suggested"),
    m(12, "ev-13", "19.1", 0.93, "strong", "Stressing record covers all L3 tendons.", [], "confirmed"),
    m(13, "ev-14", "18.2", 0.89, "strong", "Photo shows edge screens installed on L3.", [], "confirmed"),
    m(14, "ev-15", "17.1", 0.79, "partial", "Invoice lists site establishment costs; first instalment only.", ["builder sign-off on establishment"], "suggested"),
  ];

  const claimed: Record<string, number> = {
    "14.2": 18400, "14.3": 14200, "14.4": 22800, "14.5": 41250, "14.6": 5120, "15.1": 16500,
    "17.1": 6800, "18.2": 3700, "19.1": 8900, "22.3": 9600, "31.0": 6000,
  };
  const claim_items: ClaimItem[] = Object.entries(claimed).map(([code, amount], i) => ({
    id: `cli-${i + 1}`,
    claim_id: "clm-7",
    contract_item_id: ci(code),
    claimed_quantity: null,
    claimed_amount: amount,
    created_at: at(-3),
    updated_at: at(-3),
  }));

  const month = new Date(now).toLocaleString("en-AU", { month: "long", year: "numeric" });

  return {
    version: SEED_VERSION,
    session: null,
    settings: { ai_available: true },
    organisations: [
      { id: ORG, name: "Kearney Formwork Pty Ltd", created_at: t, updated_at: t },
      // second org exists only to prove isolation: nothing of theirs is ever visible
      { id: "org-other", name: "Other Subbie Pty Ltd", created_at: t, updated_at: t },
    ],
    profiles: [
      { id: ME, email: "ollie@kearneyformwork.test", organisation_id: ORG, full_name: "Ollie Reid", role: "owner", created_at: t, updated_at: t },
      { id: "usr-jas", email: "jas@kearneyformwork.test", organisation_id: ORG, full_name: "Jas Malik", role: "member", created_at: t, updated_at: t },
      { id: "usr-other", email: "sam@othersubbie.test", organisation_id: "org-other", full_name: "Sam Other", role: "owner", created_at: t, updated_at: t },
    ],
    projects: [
      { id: P, organisation_id: ORG, name: "Hume St Tower", client_name: "Bellrock Construction", site_address: "118 Hume St, Melbourne VIC",
        status: "active", start_date: date(-120), end_date: date(240), created_by: ME, created_at: t, updated_at: t },
      { id: "prj-dock", organisation_id: ORG, name: "Docklands Car Park L2", client_name: "Harbourline Builders", site_address: "9 Wharf Rd, Docklands VIC",
        status: "archived", start_date: date(-400), end_date: date(-60), created_by: ME, created_at: at(-400), updated_at: at(-60) },
      { id: "prj-secret", organisation_id: "org-other", name: "Other Org Secret Job", client_name: "Someone", site_address: "—",
        status: "active", start_date: null, end_date: null, created_by: "usr-other", created_at: t, updated_at: t },
    ],
    contracts: [
      { id: C, project_id: P, original_filename: "Subcontract_HumeSt_Formwork.pdf", storage_path: `contracts/${P}/${C}/original.pdf`,
        mime_type: "application/pdf", size_bytes: 3_480_000, page_count: 42, processing_status: "ready", error: null,
        uploaded_by: ME, created_at: t, updated_at: t, processed_at: at(-30, 9, 3) },
    ],
    contract_items,
    evidence,
    evidence_matches,
    claims: [
      { id: "clm-7", project_id: P, name: `Claim #7, ${month}`, number: 7, period_start: date(-25), period_end: date(5),
        due_date: date(9), status: "draft", created_by: ME, created_at: at(-3), updated_at: at(-3) },
    ],
    claim_items,
    variations: [
      { id: "var-1", project_id: P, code: "VAR-01", title: "Additional drainage penetrations, L3 slab", potential_variation: true,
        confidence: 0.71, reason: "Builder's foreman requested penetrations that are not shown on the contract drawings.",
        estimated_amount: 6200, related_evidence_ids: ["ev-10"], related_contract_item_id: null, notice_due: date(14),
        review_required: true, status: "flagged", created_at: at(-6) },
      { id: "var-2", project_id: P, code: "VAR-02", title: "Latent slab condition, grid B2", potential_variation: true,
        confidence: 0.78, reason: "Photo describes additional propping and formwork for a latent condition; no matching line item in the contract.",
        estimated_amount: 11500, related_evidence_ids: ["ev-8"], related_contract_item_id: null, notice_due: date(6),
        review_required: true, status: "flagged", created_at: at(-5) },
    ],
    notifications: [
      { id: "ntf-1", profile_id: ME, project_id: P, title: "AI match requires confirmation", body: "Delivery docket #4471 was matched to 14.2 with low confidence.",
        href: `/projects/${P}/review?item=${ci("14.2")}`, status: "unread", created_at: at(-1) },
      { id: "ntf-2", profile_id: ME, project_id: P, title: "Potential variation detected", body: "Latent slab condition, grid B2 — notice may be required.",
        href: `/projects/${P}/claims/clm-7`, status: "unread", created_at: at(-5) },
      { id: "ntf-3", profile_id: ME, project_id: P, title: "Deadline approaching", body: "Potential requirement for 22.3 Crane hire closes in 6 days — review contract.",
        href: `/projects/${P}/contracts/${C}/items`, status: "unread", created_at: at(-1) },
      { id: "ntf-4", profile_id: ME, project_id: P, title: "Evidence appears missing", body: "14.4 Formwork, slab soffit L3 has no linked evidence.",
        href: `/projects/${P}/review?item=${ci("14.4")}`, status: "read", created_at: at(-2) },
    ],
    audit_events: [
      { id: "aud-1", organisation_id: ORG, project_id: P, actor_id: ME, action: "contract.uploaded", entity: "contract", entity_id: C, metadata: { filename: "Subcontract_HumeSt_Formwork.pdf" }, created_at: t },
      { id: "aud-2", organisation_id: ORG, project_id: P, actor_id: null, action: "contract.extracted", entity: "contract", entity_id: C, metadata: { items: 12 }, created_at: at(-30, 9, 3) },
      { id: "aud-3", organisation_id: ORG, project_id: P, actor_id: null, action: "match.generated", entity: "evidence_match", entity_id: "em-1", metadata: { count: 11 }, created_at: at(-10) },
      { id: "aud-4", organisation_id: ORG, project_id: P, actor_id: ME, action: "match.confirmed", entity: "evidence_match", entity_id: "em-1", metadata: { item: "14.2", evidence: "EV-001" }, created_at: at(-4) },
      { id: "aud-5", organisation_id: ORG, project_id: P, actor_id: null, action: "variation.flagged", entity: "variation", entity_id: "var-2", metadata: { code: "VAR-02" }, created_at: at(-5) },
    ],
  };
}
