"use client";
// F12 Claim readiness dashboard · F13 claim evidence summary · F17 notice flags · F19 evidence graph
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useData } from "@/lib/store";
import { LIVE } from "@/lib/env";
import { read, readiness, setVariationStatus, type Readiness } from "@/lib/api";
import type { Db } from "@/lib/types";
import { ErrorState, Icon, Page, PageHeader, Progress, StateBadge, cx, fmtDate, money } from "@/components/ui";

export default function ClaimDashboard() {
  const db = useData();
  const { projectId, claimId } = useParams<{ projectId: string; claimId: string }>();
  const [view, setView] = useState<"summary" | "graph">("summary");
  if (LIVE) return <Page><ErrorState title="Live claim readiness is not available yet" body="Claims and readiness still need backend integration. You can continue reviewing evidence in Review." /></Page>;
  const c = read.claim(db, claimId);
  if (!c || c.project_id !== projectId) return <Page><ErrorState title="Claim not found" /></Page>;

  const r = readiness(db, claimId);
  const base = `/projects/${projectId}`;
  const notProven = r.values.partial + r.values.weak + r.values.missing;
  const notProvenLines = r.counts.partial + r.counts.weak + r.counts.missing;
  const varValue = r.variations.reduce((s, v) => s + (v.estimated_amount ?? 0), 0);
  const nextNotice = r.notices.find((n) => n.days != null && n.days >= 0);
  const varNotice = r.notices.find((n) => !n.definitive && n.text.startsWith("Variation") && n.days != null && n.days >= 0);

  const actions = [
    ...r.rows.filter((x) => x.state !== "strong").slice(0, 1).map((x) => `${x.item.item_code} ${x.item.description}: ${x.supportGaps.join("; ")}`),
    ...r.rows.filter((x) => x.item.notice_requirement && x.state !== "strong").slice(0, 1).map((x) => `${x.item.item_code}: ${x.item.notice_requirement}`),
    ...r.variations.filter((v) => v.status === "flagged").slice(0, 1).map((v) => `Review the potential variation for ${v.title.toLowerCase()} — consider a notice`),
    r.pendingMatches > 0 && `Confirm or reject ${r.pendingMatches} AI-suggested evidence links`,
  ].filter(Boolean).slice(0, 3) as string[];

  return (
    <Page wide>
      <PageHeader
        title="Before you send this claim"
        sub="Review confirmed evidence links and support gaps before preparing your claim."
        right={
          <>
            <span className="text-sm text-muted">{c.name} · due to the builder {fmtDate(c.due_date)}</span>
            <Link href={`${base}/claims/${c.id}/export`} className="btn-dark"><Icon.download className="h-4 w-4" />Evidence package</Link>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="rounded-2xl bg-ink p-7 text-white sm:p-9">
          <p className="text-sage">Evidence support coverage</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:gap-8">
            <p className="text-7xl font-bold leading-none sm:text-8xl">{r.coverage}%</p>
            <p className="pb-2 text-lg leading-snug">of claimed value has strong<br className="hidden sm:block" /> confirmed evidence support</p>
          </div>
          <div className="mt-6"><Progress value={r.coverage} dark /></div>
          <p className="mt-3 text-sage">{money(r.values.strong)} strong support · {money(notProven)} needs attention</p>
          <p className="mt-4 text-xs text-sage/80">Strong-support claimed value divided by total claimed value, rounded to a whole percent. Confirmed links do not certify contractual compliance or legal entitlement.</p>
        </section>
        <section className="card p-7 sm:p-9">
          <p className="font-semibold">Do these things first</p>
          {actions.length ? (
            <ol className="mt-5 space-y-4">
              {actions.map((a, i) => (
                <li key={i} className="flex gap-4">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-2 text-xs font-semibold text-muted">{i + 1}</span>
                  <span>{a}</span>
                </li>
              ))}
            </ol>
          ) : <p className="mt-5 text-muted">No support gaps identified from the current records. Check contractual requirements before submission.</p>}
        </section>
      </div>

      <div className="mt-8 space-y-3">
        <StatusRow color="bg-brand" title="Strong confirmed support" sub="Confirmed links with strong assessments and no recorded support gaps" count={`${r.counts.strong} of ${r.rows.length} lines`} value={money(r.values.strong)} valueColor="text-brand" />
        <StatusRow
          color="bg-amber" title="Evidence needs attention" sub="Missing confirmed links, weak assessments, or recorded support gaps"
          count={`${notProvenLines} lines`} value={money(notProven)} valueColor="text-amber"
          action={notProvenLines > 0 && <Link href={`${base}/review?item=${r.rows.find((x) => x.state !== "strong")?.item.id}`} className="btn-primary px-8">Fix now</Link>}
        />
        <StatusRow
          color="bg-red" title="Possible variation" sub="Work that may be outside the contract scope — review required"
          count={`${r.variations.length} event${r.variations.length === 1 ? "" : "s"}`} value={varValue ? money(varValue) : "—"} valueColor="text-red"
          action={varNotice && <span className="pill bg-red-bg px-4 py-2 text-sm text-red">Notice may close in {varNotice.days} days</span>}
        />
        <StatusRow
          color="bg-muted" title="Notice deadlines" sub={nextNotice ? `Earliest closes ${fmtDate(nextNotice.due)}, none missed so far` : "No deadlines identified"}
          count={`${r.notices.length} open`} value="—" valueColor="text-ink-2"
        />
      </div>

      {/* At-a-glance counters */}
      <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        {([
          ["Claim items", r.rows.length], ["Strong", r.counts.strong], ["Partial", r.counts.partial], ["Weak", r.counts.weak], ["Missing", r.counts.missing],
          ["Human-reviewed", `${r.reviewed} / ${r.rows.length}`], ["Potential variations", r.variations.length], ["Notice flags", r.notices.length],
        ] as const).map(([k, v]) => (
          <div key={k} className="card px-4 py-3"><p className="text-2xl font-bold">{v}</p><p className="text-xs text-muted">{k}</p></div>
        ))}
      </div>

      {r.notices.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 text-xl font-bold">Notices & obligations</h2>
          <div className="card divide-y divide-line">
            {r.notices.map((n) => (
              <div key={n.key} className="flex flex-col gap-1 px-5 py-4 sm:flex-row sm:items-center sm:gap-4">
                <Icon.clock className={cx("hidden h-5 w-5 shrink-0 sm:block", n.days != null && n.days <= 7 ? "text-red" : "text-amber")} />
                <div className="flex-1">
                  <p className="font-semibold">{n.definitive ? n.text : `Potential requirement — review contract: ${n.text}`}</p>
                  <p className="text-sm text-muted">{n.label}</p>
                </div>
                {n.due && (
                  <span className={cx("pill", n.days! < 0 ? "bg-surface-2 text-muted" : n.days! <= 7 ? "bg-red-bg text-red" : "bg-amber-bg text-amber")}>
                    {n.days! < 0 ? `Date passed ${fmtDate(n.due)}` : `Required by ${fmtDate(n.due)} · ${n.days} days`}
                  </span>
                )}
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">SubPay surfaces dates found in your contract. It does not give legal advice — check the contract wording.</p>
        </section>
      )}

      {r.variations.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 text-xl font-bold">Potential variations</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {r.variations.map((v) => (
              <div key={v.id} className="card p-5">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold">{v.code} {v.title}</p>
                  <span className="pill bg-red-bg text-red">AI flag · {Math.round(v.confidence * 100)}%</span>
                </div>
                <p className="mt-1 text-sm text-muted">{v.reason}</p>
                <p className="mt-2 text-sm">Evidence: {v.related_evidence_ids.map((id) => db.evidence.find((e) => e.id === id)?.code).join(", ")}{v.estimated_amount ? ` · est. ${money(v.estimated_amount)}` : ""}</p>
                <div className="mt-3 flex items-center gap-2">
                  {v.status === "flagged" ? (
                    <>
                      <button className="btn-outline btn-sm" onClick={() => setVariationStatus(v.id, "acknowledged")}>Acknowledge</button>
                      <button className="btn-outline btn-sm" onClick={() => setVariationStatus(v.id, "dismissed")}>Not a variation</button>
                    </>
                  ) : <span className="text-sm font-semibold text-brand-dark">Acknowledged by a person — still not an approved variation</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mt-10">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xl font-bold">Claim evidence summary</h2>
          <div className="inline-flex rounded-full border border-line bg-white p-1 text-sm">
            {(["summary", "graph"] as const).map((v) => (
              <button key={v} onClick={() => setView(v)} className={cx("rounded-full px-4 py-1.5", view === v ? "bg-ink text-white" : "text-muted")}>
                {v === "summary" ? "Table" : "Evidence graph"}
              </button>
            ))}
          </div>
        </div>
        {view === "summary" ? <Summary db={db} r={r} base={base} /> : <Graph db={db} r={r} />}
      </section>
    </Page>
  );
}

function StatusRow({ color, title, sub, count, value, valueColor, action }: {
  color: string; title: string; sub: string; count: string; value: string; valueColor: string; action?: React.ReactNode;
}) {
  return (
    <div className="card relative grid grid-cols-[auto_1fr] items-center gap-x-5 gap-y-2 overflow-hidden py-5 pl-8 pr-6 md:grid-cols-[auto_1fr_9rem_9rem_12rem]">
      <span className={cx("absolute inset-y-0 left-0 w-1.5", color)} />
      <span className={cx("h-6 w-6 rounded-full", color)} />
      <div>
        <p className="text-lg font-bold">{title}</p>
        <p className="text-muted">{sub}</p>
      </div>
      <p className="col-start-2 md:col-start-auto"><span className="font-bold">{count}</span><span className="block text-sm text-muted">in this claim</span></p>
      <p className={cx("col-start-2 text-2xl font-bold md:col-start-auto", valueColor)}>{value}</p>
      <div className="col-start-2 md:col-start-auto md:text-right">{action}</div>
    </div>
  );
}

function Summary({ db, r, base }: { db: Db; r: Readiness; base: string }) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[56rem] text-sm">
        <thead className="bg-surface-2 text-left text-muted">
          <tr>
            <th className="px-4 py-3 font-semibold">Item</th>
            <th className="px-4 py-3 text-right font-semibold">Claimed</th>
            <th className="px-4 py-3 font-semibold">Linked evidence</th>
            <th className="px-4 py-3 font-semibold">Evidence status</th>
            <th className="px-4 py-3 font-semibold">AI reasoning</th>
            <th className="px-4 py-3 font-semibold">Possibly missing</th>
          </tr>
        </thead>
        <tbody>
          {r.rows.map((row) => {
            const live = row.matches.filter((m) => m.status !== "rejected");
            const top = live.filter((m) => m.source === "ai").sort((a, b) => b.confidence - a.confidence)[0];
            return (
              <tr key={row.claimItem.id} className="border-t border-line align-top">
                <td className="px-4 py-3">
                  <Link href={`${base}/review?item=${row.item.id}`} className="font-semibold hover:underline">{row.item.item_code} {row.item.description}</Link>
                  <p className="text-xs text-muted">{row.item.source_reference}</p>
                </td>
                <td className="px-4 py-3 text-right font-semibold">{money(row.claimItem.claimed_amount)}</td>
                <td className="px-4 py-3">
                  {live.length === 0 && <span className="text-muted">None</span>}
                  {live.map((m) => {
                    const ev = db.evidence.find((e) => e.id === m.evidence_id);
                    return (
                      <span key={m.id} className={cx("mb-1 mr-1 inline-block rounded-md px-1.5 py-0.5 text-xs", m.status === "confirmed" ? "bg-mint text-brand-dark" : "border border-dashed border-amber text-amber")}
                        title={m.status === "confirmed" ? `Confirmed by ${read.actor(db, m.confirmed_by)}` : "AI suggestion — awaiting human review"}>
                        {m.status === "confirmed" ? "✓" : "AI?"} {ev?.code}
                      </span>
                    );
                  })}
                </td>
                <td className="px-4 py-3">
                  <StateBadge state={row.state} />
                  <p className="text-xs text-muted">{row.confirmedCount} human-confirmed · {row.pending} awaiting</p>
                </td>
                <td className="max-w-xs px-4 py-3 text-muted">{top ? top.reason : "—"}</td>
                <td className="px-4 py-3 text-amber">{row.supportGaps.join("; ") || "No support gaps recorded"}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-line font-semibold"><td className="px-4 py-3">Total claimed</td><td className="px-4 py-3 text-right">{money(r.total)}</td><td colSpan={4} /></tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Contract items ↔ evidence ↔ potential variations, drawn from the relational data (no graph DB). */
function Graph({ db, r }: { db: Db; r: Readiness }) {
  const [focus, setFocus] = useState<string | null>(null);
  const links = r.rows.flatMap((row) => row.matches.filter((m) => m.status !== "rejected").map((m) => ({ ...m, row })));
  const evIds = [...new Set([...links.map((l) => l.evidence_id), ...r.variations.flatMap((v) => v.related_evidence_ids)])];
  const ROW = 46, W = 960, H = Math.max(r.rows.length, evIds.length, r.variations.length) * ROW + 40;
  const yItem = (i: number) => 40 + i * ROW;
  const yEv = (id: string) => 40 + evIds.indexOf(id) * ROW;
  const on = (ids: string[]) => !focus || ids.includes(focus);

  return (
    <div className="card overflow-x-auto p-4">
      <div className="mb-2 flex flex-wrap gap-4 px-2 text-xs text-muted">
        <span><span className="mr-1 inline-block h-0.5 w-6 bg-brand align-middle" />Human-confirmed</span>
        <span><span className="mr-1 inline-block w-6 border-t-2 border-dashed border-amber align-middle" />AI suggestion</span>
        <span><span className="mr-1 inline-block w-6 border-t-2 border-dotted border-red align-middle" />Potential variation</span>
        <span>Hover a node to trace it.</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[48rem] w-full" onMouseLeave={() => setFocus(null)}>
        <text x={10} y={20} className="fill-muted text-[12px]">Claim line (contract item)</text>
        <text x={400} y={20} className="fill-muted text-[12px]">Evidence</text>
        <text x={720} y={20} className="fill-muted text-[12px]">Potential variation</text>
        {links.map((l) => {
          const i = r.rows.indexOf(l.row);
          return (
            <path key={l.id} d={`M290 ${yItem(i) + 16} C 345 ${yItem(i) + 16}, 345 ${yEv(l.evidence_id) + 16}, 400 ${yEv(l.evidence_id) + 16}`}
              fill="none" strokeWidth={2} className={l.status === "confirmed" ? "stroke-brand" : "stroke-amber"} strokeDasharray={l.status === "confirmed" ? undefined : "6 4"}
              opacity={on([l.row.item.id, l.evidence_id]) ? 1 : 0.12} />
          );
        })}
        {r.variations.map((v, vi) => v.related_evidence_ids.map((eid) => (
          <path key={v.id + eid} d={`M630 ${yEv(eid) + 16} C 675 ${yEv(eid) + 16}, 675 ${yItem(vi) + 16}, 720 ${yItem(vi) + 16}`}
            fill="none" strokeWidth={2} strokeDasharray="2 4" className="stroke-red" opacity={on([v.id, eid]) ? 1 : 0.12} />
        )))}
        {r.rows.map((row, i) => (
          <g key={row.item.id} onMouseEnter={() => setFocus(row.item.id)} opacity={on([row.item.id, ...row.matches.map((m) => m.evidence_id)]) ? 1 : 0.3}>
            <rect x={0} y={yItem(i)} width={290} height={32} rx={8} className="fill-white stroke-line" />
            <circle cx={14} cy={yItem(i) + 16} r={5} className={row.state === "strong" ? "fill-brand" : row.state === "partial" ? "fill-amber" : row.state === "weak" ? "fill-red" : "fill-muted"} />
            <text x={26} y={yItem(i) + 20} className="fill-ink-2 text-[12px] font-semibold">{`${row.item.item_code} ${row.item.description}`.slice(0, 38)}</text>
          </g>
        ))}
        {evIds.map((id) => {
          const ev = db.evidence.find((e) => e.id === id)!;
          return (
            <g key={id} onMouseEnter={() => setFocus(id)} opacity={on([id, ...links.filter((l) => l.evidence_id === id).map((l) => l.row.item.id)]) ? 1 : 0.3}>
              <rect x={400} y={yEv(id)} width={230} height={32} rx={8} className="fill-surface stroke-line" />
              <text x={412} y={yEv(id) + 20} className="fill-ink-2 text-[12px]">{`${ev.code} · ${ev.title}`.slice(0, 32)}</text>
            </g>
          );
        })}
        {r.variations.map((v, vi) => (
          <g key={v.id} onMouseEnter={() => setFocus(v.id)}>
            <rect x={720} y={yItem(vi)} width={236} height={32} rx={8} className="fill-red-bg stroke-red/40" />
            <text x={732} y={yItem(vi) + 20} className="fill-red text-[12px] font-semibold">{`${v.code} ${v.title}`.slice(0, 32)}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
