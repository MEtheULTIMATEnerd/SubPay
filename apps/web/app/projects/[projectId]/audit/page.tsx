"use client";
// F15 Audit trail — append-only; there is no UI or API to edit or delete events.
import { useParams } from "next/navigation";
import { useState } from "react";
import { useData } from "@/lib/store";
import { read } from "@/lib/api";
import { LIVE } from "@/lib/env";
import { EmptyState, ErrorState, Page, PageHeader, cx, fmtDateTime } from "@/components/ui";

const FIXTURE_IDS = new Set(["aud-1", "aud-2", "aud-3", "aud-4", "aud-5"]);

const LABEL: Record<string, string> = {
  "project.created": "created the project", "project.updated": "edited project details", "project.archived": "archived the project", "project.restored": "restored the project",
  "contract.uploaded": "uploaded a contract", "contract.extracted": "extracted a claim schedule",
  "contract_item.edited": "edited a contract item", "contract_item.confirmed": "confirmed a contract item", "contract_item.rejected": "rejected a contract item", "contract_item.draft": "reopened a contract item",
  "evidence.uploaded": "uploaded evidence", "evidence.edited": "edited evidence details", "evidence.archived": "archived evidence", "evidence.restored": "restored evidence",
  "match.generated": "generated match suggestions", "match.confirmed": "confirmed a match", "match.rejected": "rejected a match", "match.reopened": "reopened a match",
  "match.edited": "moved evidence to a different line", "match.linked": "linked evidence manually",
  "variation.flagged": "flagged a potential variation", "variation.acknowledged": "acknowledged a potential variation", "variation.dismissed": "dismissed a potential variation",
  "claim.created": "created a claim", "package.exported": "exported an evidence package",
  "package.download_initiated": "initiated a JSON package download",
  "package.print_initiated": "opened package printing (PDF save not verified)",
};

export default function AuditPage() {
  const db = useData();
  const { projectId } = useParams<{ projectId: string }>();
  const [who, setWho] = useState<"all" | "human" | "ai">("all");
  if (LIVE) return <Page><ErrorState title="Live audit is not available yet" body="The audit trail still needs backend integration." /></Page>;
  const events = read.audit(db, projectId)
    .filter((a) => who === "all" || (who === "ai" ? !a.actor_id : !!a.actor_id))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <Page>
      <PageHeader title="Audit trail" sub="Demo activity saved in this browser. Seeded examples are labelled; this is not a tamper-proof record." right={
        <div className="inline-flex rounded-full border border-line bg-white p-1 text-sm">
          {(["all", "human", "ai"] as const).map((w) => (
            <button key={w} onClick={() => setWho(w)} className={cx("rounded-full px-4 py-1.5", who === w ? "bg-ink text-white" : "text-muted")}>
              {w === "all" ? "All" : w === "human" ? "People" : "SubPay AI"}
            </button>
          ))}
        </div>
      } />
      {events.length === 0 ? <EmptyState title="No events yet" /> : (
        <ol className="card divide-y divide-line">
          {events.map((a) => (
            <li key={a.id} className="flex gap-4 px-5 py-4">
              <span className={cx("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold", a.actor_id ? "bg-mint text-brand-dark" : "bg-surface-2 text-muted")}>
                {a.actor_id ? read.actor(db, a.actor_id).split(" ").map((s) => s[0]).join("") : "AI"}
              </span>
              <div className="min-w-0 flex-1">
                <p><span className="font-semibold">{read.actor(db, a.actor_id)}</span> {a.action === "package.exported" && a.metadata.format === "pdf" ? "recorded a legacy PDF export action (PDF save not verified)" : LABEL[a.action] ?? a.action}</p>
                {FIXTURE_IDS.has(a.id) && <p className="text-xs text-muted">Seeded demo example</p>}
                {Object.keys(a.metadata).length > 0 && (
                  <p className="break-words text-sm text-muted">
                    {Object.entries(a.metadata).filter(([k]) => k !== "before").map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ")}
                  </p>
                )}
              </div>
              <time dateTime={a.created_at} className="shrink-0 text-sm text-muted">{fmtDateTime(a.created_at)}</time>
            </li>
          ))}
        </ol>
      )}
    </Page>
  );
}
