// Shared entity shapes. Mirrors the agreed contracts in the team prompts
// (docs/api-contracts.md) so the mock service can be swapped for FastAPI.

export type Role = "owner" | "member";
export type ProcessingStatus = "uploaded" | "processing" | "ready" | "failed";
export type ReviewStatus = "draft" | "confirmed" | "rejected";
export type EvidenceType = "photo" | "document" | "docket" | "message" | "other";
export type Assessment = "strong" | "partial" | "weak";
export type Completeness = Assessment | "missing";
export type MatchStatus = "suggested" | "confirmed" | "rejected";
export type NotificationStatus = "unread" | "read" | "dismissed";

export interface Organisation { id: string; name: string; created_at: string; updated_at: string }

export interface Profile {
  id: string;
  email: string;
  organisation_id: string;
  full_name: string;
  role: Role;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  organisation_id: string;
  name: string;
  client_name: string;
  site_address: string;
  status: "active" | "archived";
  start_date: string | null;
  end_date: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface Contract {
  id: string;
  project_id: string;
  original_filename: string;
  storage_path: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  processing_status: ProcessingStatus;
  error: string | null;
  uploaded_by: string;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
}

export interface ContractItem {
  id: string;
  contract_id: string;
  item_code: string;
  description: string;
  quantity: number | null;
  unit: string | null;
  rate: number | null;
  amount: number | null;
  conditions: string | null;
  notice_requirement: string | null;
  due_date: string | null;
  extraction_confidence: number | null;
  review_status: ReviewStatus;
  /** true once a human has changed any AI-extracted field */
  edited_by_human: boolean;
  reviewed_by: string | null;
  source_reference: string | null;
  /** The values exactly as the AI returned them. Set by the API; absent in demo mode. */
  extracted_values?: Record<string, unknown> | null;
  /** Position in the contract's schedule. Set by the API; absent in demo mode. */
  sort_order?: number;
  created_at: string;
  updated_at: string;
}

export interface Evidence {
  id: string;
  code: string;
  project_id: string;
  uploaded_by: string;
  storage_path: string;
  original_filename: string;
  mime_type: string;
  evidence_type: EvidenceType;
  captured_at: string;
  title: string;
  description: string;
  metadata: { location: string | null; source: string; tags: string[]; author?: string };
  /** downscaled preview for images; ponytail: real files belong in Supabase Storage */
  thumbnail: string | null;
  processing_status: ProcessingStatus;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface EvidenceMatch {
  id: string;
  evidence_id: string;
  contract_item_id: string;
  confidence: number;
  assessment: Assessment;
  reason: string;
  missing_evidence: string[];
  status: MatchStatus;
  source: "ai" | "human";
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Claim {
  id: string;
  project_id: string;
  name: string;
  number: number;
  period_start: string;
  period_end: string;
  due_date: string;
  status: "draft" | "ready" | "exported";
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ClaimItem {
  id: string;
  claim_id: string;
  contract_item_id: string;
  claimed_quantity: number | null;
  claimed_amount: number;
  created_at: string;
  updated_at: string;
}

export interface Variation {
  id: string;
  project_id: string;
  code: string;
  title: string;
  potential_variation: true;
  confidence: number;
  reason: string;
  estimated_amount: number | null;
  related_evidence_ids: string[];
  related_contract_item_id: string | null;
  notice_due: string | null;
  review_required: boolean;
  status: "flagged" | "acknowledged" | "dismissed";
  created_at: string;
}

export interface Notification {
  id: string;
  profile_id: string;
  project_id: string | null;
  title: string;
  body: string;
  href: string | null;
  status: NotificationStatus;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  organisation_id: string;
  project_id: string | null;
  actor_id: string | null; // null = SubPay AI
  action: string;
  entity: string;
  entity_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Db {
  version: number;
  session: { profile_id: string } | null;
  settings: { ai_available: boolean };
  organisations: Organisation[];
  profiles: Profile[];
  projects: Project[];
  contracts: Contract[];
  contract_items: ContractItem[];
  evidence: Evidence[];
  evidence_matches: EvidenceMatch[];
  claims: Claim[];
  claim_items: ClaimItem[];
  variations: Variation[];
  notifications: Notification[];
  audit_events: AuditEvent[];
}
