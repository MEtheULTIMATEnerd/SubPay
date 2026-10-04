"use client";
// F14 Evidence package export. PDF via the browser's print-to-PDF (simplest reliable MVP), plus structured JSON.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useData } from "@/lib/store";
import { read, readiness, recordExport, type Readiness } from "@/lib/api";
import type { Db } from "@/lib/types";
import { Banner, ErrorState, Icon, Page, PageHeader, fmtDate, fmtDateTime, money } from "@/components/ui";

export default function ExportPage() {
  const db = useData();
  const { projectId, claimId } = useParams<{ projectId: string; claimId: string }>();
  const c = read.claim(db, claimId);
  if (!c || c.project_id !== projectId) return <Page><ErrorState title="Claim not found" /></Page>;

  const r = readiness(db, claimId);
  const project = read.project(db, projectId)!;
  const org = read.org(db);
  const annex = annexure(db, r);
  const confirmedLines = r.rows.filter((x) => x.matches.some((m) => m.status === "confirmed"));

  const sections = [
    ["Claim summary and cover note", "1 page"],
    ["Line-item schedule with clause references", `${r.rows.length} lines`],
    ["Indexed evidence annexure", `${annex.length} items, human-confirmed links only`],
    ["Missing or weak evidence", `${r.counts.partial + r.counts.weak + r.counts.missing} lines flagged`],
    ["Potential variations flagged for review", `${r.variations.length} events`],
    ["Notice and deadline flags", `${r.notices.length} identified`],
    ["Audit summary of human confirmations", `${r.reviewed} of ${r.rows.length} lines reviewed`],
  ];

  function downloadJson() {
    const blob = new Blob([JSON.stringify(packageJson(db, r), null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `SubPay_${project.name.replace(/\W+/g, "_")}_Claim${c!.number}.json` });
    a.click();
    URL.revokeObjectURL(a.href);
    recordExport(claimId, "json");
  }

  return (
    <>
      <div className="print:hidden">
        <Page wide>
          <PageHeader
            title="Your claim pack, in the builder's format"
            sub="Nothing changes for the builder. They receive the file they always receive."
            right={<Link href={`/projects/${projectId}/claims/${claimId}`} className="btn-outline"><Icon.back className="h-4 w-4" />Readiness</Link>}
          />
          {r.pendingMatches > 0 && (
            <div className="mb-6 rounded-xl bg-amber-bg px-5 py-4 text-amber">
              <p className="font-semibold">{r.pendingMatches} AI suggestions are still unreviewed</p>
              <p className="text-sm">Unconfirmed suggestions are excluded from the evidence annexure. <Link href={`/projects/${projectId}/review`} className="underline">Review them first</Link> or export anyway.</p>
            </div>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="card p-6 sm:p-8">
              <p className="mb-6 font-semibold">What goes in the pack</p>
              <ul className="space-y-3">
                {sections.map(([t, s]) => (
                  <li key={t} className="flex items-center gap-4 rounded-xl border border-line bg-surface/50 px-5 py-4">
                    <Icon.doc className="h-7 w-7 shrink-0 text-ink-2" />
                    <div className="flex-1"><p className="font-semibold">{t}</p><p className="text-sm text-muted">{s}</p></div>
                    <Icon.checkCircle className="h-7 w-7 shrink-0 text-brand" />
                  </li>
                ))}
              </ul>
              <p className="mt-6 text-muted">Every evidence item numbered and cross-referenced · AI-generated text labelled throughout</p>
            </section>

            <section className="card p-6 sm:p-8">
              <p className="mb-6 font-semibold">Preview</p>
              <div className="rounded-xl border border-line p-6">
                <p className="text-2xl font-bold">Progress claim #{c.number}</p>
                <p className="text-muted">{org.name} → {project.client_name}</p>
                <hr className="my-5 border-line" />
                <ul className="space-y-3">
                  {r.rows.slice(0, 5).map((x) => (
                    <li key={x.claimItem.id} className="grid grid-cols-[1fr_auto_4.5rem] gap-3">
                      <span className="truncate">{x.item.item_code} {x.item.description}</span>
                      <span className="font-semibold">{money(x.claimItem.claimed_amount)}</span>
                      <span className="text-right text-sm text-brand-dark">{x.matches.filter((m) => m.status === "confirmed").length} items</span>
                    </li>
                  ))}
                  {r.rows.length > 5 && (
                    <li className="grid grid-cols-[1fr_auto_4.5rem] gap-3 text-muted">
                      <span>+ {r.rows.length - 5} more lines</span>
                      <span className="font-semibold">{money(r.rows.slice(5).reduce((s, x) => s + x.claimItem.claimed_amount, 0))}</span>
                      <span />
                    </li>
                  )}
                </ul>
                <hr className="my-5 border-line" />
                <p className="flex justify-between text-lg font-bold"><span>Total claimed</span><span>{money(r.total)}</span></p>
                <p className="mt-2 text-sm text-muted">Evidence annexure attached, items A1–A{annex.length} · {confirmedLines.length} lines with confirmed evidence</p>
                <div className="mt-6 flex flex-col gap-3 sm:flex-row">
                  <button className="btn-primary flex-1 py-3.5 text-base" onClick={() => { recordExport(claimId, "pdf"); setTimeout(() => window.print(), 50); }}>Export claim pack (PDF)</button>
                  <button className="btn-outline flex-1 py-3.5 text-base" onClick={downloadJson}>Download structured JSON</button>
                </div>
              </div>
              {c.status === "exported" && <p className="mt-3 text-sm text-brand-dark">Exported — recorded in the audit trail.</p>}
            </section>
          </div>
          <div className="mt-8">
            <Banner title="Your evidence stays in your account after the claim is paid." body="Kept for disputes, retention claims and defects liability. SubPay never sends the claim for you." />
          </div>
        </Page>
      </div>
      <PrintDocument db={db} r={r} />
    </>
  );
}

function annexure(db: Db, r: Readiness) {
  const ids = [...new Set(r.rows.flatMap((x) => x.matches.filter((m) => m.status === "confirmed").map((m) => m.evidence_id)))];
  return ids.map((id, i) => ({ ref: `A${i + 1}`, ev: db.evidence.find((e) => e.id === id)! }));
}

function packageJson(db: Db, r: Readiness) {
  const annex = annexure(db, r);
  const ref = (id: string) => annex.find((a) => a.ev.id === id)?.ref ?? null;
  return {
    generated_at: new Date().toISOString(),
    disclaimer: "Evidence package prepared with SubPay. Not legally certified. AI-generated content is labelled; only human-confirmed links are treated as supporting evidence.",
    claim: { name: r.claim.name, period_start: r.claim.period_start, period_end: r.claim.period_end, total_claimed: r.total, evidence_support_coverage_pct: r.coverage },
    items: r.rows.map((x) => ({
      item_code: x.item.item_code, description: x.item.description, source_reference: x.item.source_reference,
      claimed_amount: x.claimItem.claimed_amount, evidence_status: x.state,
      evidence: x.matches.filter((m) => m.status !== "rejected").map((m) => ({
        annexure_ref: m.status === "confirmed" ? ref(m.evidence_id) : null,
        evidence_code: db.evidence.find((e) => e.id === m.evidence_id)?.code,
        human_status: m.status, confirmed_by: m.confirmed_by ? read.actor(db, m.confirmed_by) : null, confirmed_at: m.confirmed_at,
        ai: m.source === "ai" ? { confidence: m.confidence, assessment: m.assessment, reason: m.reason, missing_evidence: m.missing_evidence } : null,
      })),
    })),
    annexure: annex.map((a) => ({ ref: a.ref, code: a.ev.code, title: a.ev.title, type: a.ev.evidence_type, captured_at: a.ev.captured_at, location: a.ev.metadata.location, file: a.ev.storage_path })),
    potential_variations: r.variations.map((v) => ({ code: v.code, title: v.title, ai_confidence: v.confidence, reason: v.reason, status: v.status, review_required: v.review_required })),
    notice_flags: r.notices.map((n) => ({ item: n.label, requirement: n.text, due: n.due, certainty: n.definitive ? "identified" : "potential — review contract" })),
  };
}

/** Only visible when printing — becomes the PDF. */
function PrintDocument({ db, r }: { db: Db; r: Readiness }) {
  const project = read.project(db, r.claim.project_id)!;
  const org = read.org(db);
  const annex = annexure(db, r);
  const ref = (id: string) => annex.find((a) => a.ev.id === id)?.ref;
  return (
    <article className="hidden p-8 text-[11pt] text-black print:block">
      <header className="border-b-2 border-black pb-4">
        <p className="text-sm">Evidence package · generated {fmtDateTime(new Date().toISOString())}</p>
        <h1 className="text-3xl font-bold">Progress claim #{r.claim.number} — {project.name}</h1>
        <p>{org.name} → {project.client_name} · Period {fmtDate(r.claim.period_start)} – {fmtDate(r.claim.period_end)}</p>
      </header>

      <h2 className="mt-6 text-xl font-bold">1. Claim summary</h2>
      <p>Total claimed {money(r.total)} across {r.rows.length} lines. {r.counts.strong} lines ({money(r.values.strong)}) have strong, human-confirmed evidence; {r.counts.partial} partial; {r.counts.weak} weak; {r.counts.missing} without evidence. Evidence support coverage: {r.coverage}% of claimed value.</p>

      <h2 className="mt-6 text-xl font-bold">2–3. Contract items and evidence mappings</h2>
      <table className="mt-2 w-full border-collapse text-[9pt]">
        <thead><tr className="border-b border-black text-left"><th className="py-1">Item</th><th>Clause</th><th className="text-right">Claimed</th><th className="pl-2">Human-confirmed evidence</th><th>Status</th></tr></thead>
        <tbody>
          {r.rows.map((x) => (
            <tr key={x.claimItem.id} className="border-b border-gray-300 align-top">
              <td className="py-1">{x.item.item_code} {x.item.description}</td>
              <td>{x.item.source_reference}</td>
              <td className="text-right">{money(x.claimItem.claimed_amount)}</td>
              <td className="pl-2">{x.matches.filter((m) => m.status === "confirmed").map((m) => `${ref(m.evidence_id)} (confirmed by ${read.actor(db, m.confirmed_by)})`).join("; ") || "—"}</td>
              <td>{x.state}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 className="mt-6 text-xl font-bold">4. Evidence annexure</h2>
      <ol className="mt-2 text-[9pt]">
        {annex.map((a) => <li key={a.ref}><strong>{a.ref}</strong> — {a.ev.code} {a.ev.title}, {a.ev.evidence_type}, {fmtDateTime(a.ev.captured_at)}{a.ev.metadata.location ? `, ${a.ev.metadata.location}` : ""} · {a.ev.storage_path}</li>)}
      </ol>

      <h2 className="mt-6 text-xl font-bold">5. Missing or weak evidence</h2>
      <ul className="text-[9pt]">
        {r.rows.filter((x) => x.state !== "strong").map((x) => (
          <li key={x.item.id}>{x.item.item_code} {x.item.description} — {x.state}; {[...new Set(x.matches.flatMap((m) => m.missing_evidence))].join(", ") || "no supporting evidence linked"} <em>(AI-identified)</em></li>
        ))}
      </ul>

      <h2 className="mt-6 text-xl font-bold">6. Potential variations (AI flags — review required)</h2>
      <ul className="text-[9pt]">{r.variations.map((v) => <li key={v.id}>{v.code} {v.title} — {v.reason} Status: {v.status}. Not an approved variation.</li>)}</ul>

      <h2 className="mt-6 text-xl font-bold">7. Notice and deadline flags</h2>
      <ul className="text-[9pt]">{r.notices.map((n) => <li key={n.key}>{n.label}: {n.definitive ? "" : "Potential requirement — review contract. "}{n.text}{n.due ? ` — by ${fmtDate(n.due)}` : ""}</li>)}</ul>

      <h2 className="mt-6 text-xl font-bold">8. Human confirmation status</h2>
      <p>{r.reviewed} of {r.rows.length} lines fully reviewed by a person. {r.pendingMatches} AI suggestions remain unreviewed and are excluded from the annexure.</p>

      <footer className="mt-8 border-t border-black pt-3 text-[8pt]">
        9. Generated {new Date().toISOString()} by SubPay. This package organises evidence; it is not legally certified and does not determine entitlement. AI-generated content is labelled as such.
      </footer>
    </article>
  );
}
