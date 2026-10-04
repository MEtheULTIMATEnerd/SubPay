// Deterministic mock AI provider (Arya's layer). Same input/output shapes as the
// agreed AI contract, so the real provider replaces this file, not its callers.
//
// Confidence methodology (mock): keyword-overlap between evidence text and the
// contract item description, mapped linearly to 0.40–0.95. It is a placeholder
// heuristic, NOT a calibrated or validated score.
import type { Assessment, ContractItem, Evidence } from "./types";

export class AiUnavailableError extends Error {
  constructor() {
    super("AI analysis unavailable. You can continue reviewing evidence manually.");
  }
}

export interface ExtractedItem {
  item_code: string;
  description: string;
  quantity: number | null;
  unit: string | null;
  rate: number | null;
  amount: number | null;
  conditions: string | null;
  notice_requirement: string | null;
  due_date: string | null;
  confidence: number;
  source_reference: string | null;
}
export interface ExtractionResult { contract_id: string; items: ExtractedItem[] }

export interface MatchSuggestion {
  contract_item_id: string;
  confidence: number;
  assessment: Assessment;
  reason: string;
  missing_evidence: string[];
}
export interface MatchResult { evidence_id: string; matches: MatchSuggestion[] }

export interface VariationFlag {
  potential_variation: true;
  confidence: number;
  reason: string;
  related_evidence_ids: string[];
  review_required: true;
}

const STOP = new Set(["and", "the", "for", "of", "to", "in", "on", "at", "with", "a", "an", "is", "by", "from", "all", "per", "item"]);

export function tokens(text: string): string[] {
  const norm = text.toLowerCase().replace(/level\s*(\d+)/g, "l$1").replace(/[^a-z0-9 ]+/g, " ");
  return [...new Set(norm.split(/\s+/).filter((w) => w.length > 1 && !STOP.has(w)).map((w) => w.replace(/s$/, "")))];
}

export function extractContract(contract_id: string, filename: string): ExtractionResult {
  // A fixed schedule regardless of the file: the mock never reads the document.
  const base = /fitout|electrical/i.test(filename);
  const rows: [string, string, number | null, string | null, number | null, number | null, number, string | null][] = base
    ? [
        ["4.2", "Electrical conduit installation", 120, "m", 45, 5400, 0.91, null],
        ["4.3", "Cable tray installation", 80, "m", 60, 4800, 0.88, null],
        ["4.5", "Switchboard installation", 1, "item", 12500, 12500, 0.84, "Notify builder 5 days before energisation"],
        ["6.1", "Lighting fit-off", null, null, null, 7600, 0.67, null],
      ]
    : [
        ["1.1", "Preliminaries and site establishment", 1, "item", 4500, 4500, 0.82, null],
        ["2.1", "Formwork, slab edges", 180, "m²", 75, 13500, 0.9, null],
        ["2.2", "Formwork, columns", 96, "m²", 95, 9120, 0.87, null],
        ["3.1", "Concrete supply and place", 110, "m³", 245, 26950, 0.86, "Notify builder 48 hours before each pour"],
        ["5.4", "Delay costs, standing time", null, "hr", null, null, 0.55, "Written direction required within 5 business days"],
      ];
  return {
    contract_id,
    items: rows.map(([code, description, quantity, unit, rate, amount, confidence, notice]) => ({
      item_code: code, description, quantity, unit, rate, amount,
      conditions: null, notice_requirement: notice, due_date: null, confidence,
      source_reference: `Schedule of rates, item ${code}`,
    })),
  };
}

export function matchEvidence(ev: Pick<Evidence, "id" | "title" | "description" | "evidence_type">, items: ContractItem[]): MatchResult {
  const evTokens = new Set(tokens(`${ev.title} ${ev.description}`));
  const scored = items
    .filter((i) => i.review_status !== "rejected")
    .map((item) => {
      const it = tokens(item.description);
      const hits = it.filter((t) => evTokens.has(t));
      return { item, hits, score: it.length ? hits.length / it.length : 0 };
    })
    .filter((s) => s.score >= 0.34)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3);

  return {
    evidence_id: ev.id,
    matches: scored.map(({ item, hits, score }) => {
      const confidence = Math.round((0.4 + 0.55 * score) * 100) / 100;
      const assessment: Assessment = confidence >= 0.85 ? "strong" : confidence >= 0.7 ? "partial" : "weak";
      const missing =
        assessment === "strong" && ev.evidence_type === "photo" ? []
        : ev.evidence_type === "photo" ? ["quantity confirmation"]
        : ["photo of completed work"];
      return {
        contract_item_id: item.id,
        confidence,
        assessment,
        reason: `Evidence mentions ${hits.map((h) => `"${h}"`).join(", ")}, which appear in ${item.item_code} ${item.description}.`,
        missing_evidence: missing,
      };
    }),
  };
}

const CHANGE_WORDS = /\b(additional|extra|latent|unforeseen|changed|not on (the )?drawings|variation|instructed)\b/i;

export function detectVariation(ev: Pick<Evidence, "id" | "description" | "title">, result: MatchResult): VariationFlag | null {
  const best = result.matches[0]?.confidence ?? 0;
  if (best >= 0.85 || !CHANGE_WORDS.test(`${ev.title} ${ev.description}`)) return null;
  return {
    potential_variation: true,
    confidence: 0.7,
    reason: "Evidence describes additional or changed work with no strong matching contract line item.",
    related_evidence_ids: [ev.id],
    review_required: true,
  };
}
