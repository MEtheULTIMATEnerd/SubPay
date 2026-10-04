"use client";
// F10 Human match confirmation. AI suggestions and human decisions are always shown separately.
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { Suspense, useState } from "react";
import { useData } from "@/lib/store";
import { completeness, linkEvidence, read, readiness, reviewMatch } from "@/lib/api";
import type { ContractItem, Db, EvidenceMatch } from "@/lib/types";
import {
  AiBadge, Banner, Dialog, EmptyState, EvidenceIcon, Icon, Notice, Page, PageHeader, Progress, StateBadge, cx, fmtDateTime, money, stateColor,
} from "@/components/ui";

export default function ReviewPage() {
  return <Suspense><Review /></Suspense>;
}

function Review() {
  const db = useData();
  const router = useRouter();
  const params = useSearchParams();
  const { projectId } = useParams<{ projectId: string }>();
  const me = read.me(db)!;

  const items = read.projectItems(db, projectId)
    .filter((i) => i.review_status !== "rejected")
    .sort((a, b) => a.item_code.localeCompare(b.item_code, undefined, { numeric: true }));
  const evidence = read.evidence(db, projectId).filter((e) => !e.archived);
  const matches = read.matches(db, projectId);
  const claim = read.claims(db, projectId).at(-1);
  const r = claim ? readiness(db, claim.id) : null;

  const fromEvidence = params.get("evidence") && matches.find((m) => m.evidence_id === params.get("evidence"))?.contract_item_id;
  const firstPending = items.find((i) => matches.some((m) => m.contract_item_id === i.id && m.status === "suggested"));
  // Pin the line once acted on, so it doesn't jump to the next pending line after an approval.
  const [pinned, setPinned] = useState<string | null>(null);
  const itemId = params.get("item") ?? pinned ?? fromEvidence ?? firstPending?.id ?? items[0]?.id;
  const item = items.find((i) => i.id === itemId);
  const go = (id: string) => router.replace(`/projects/${projectId}/review?item=${id}`, { scroll: false });

  const [changing, setChanging] = useState<EvidenceMatch | null>(null);
  const [linking, setLinking] = useState(false);
  const decide = (id: string, status: EvidenceMatch["status"]) => { setPinned(itemId); reviewMatch(id, status); };

  if (!item)
    return <Page><EmptyState title="Nothing to review yet" body="Confirm your claim schedule and upload evidence first. SubPay will then suggest which evidence supports which line." /></Page>;

  const lineMatches = matches
    .filter((m) => m.contract_item_id === item.id && m.status !== "rejected")
    .sort((a, b) => b.confidence - a.confidence);
  const rejected = matches.filter((m) => m.contract_item_id === item.id && m.status === "rejected");
  const approved = lineMatches.filter((m) => m.status === "confirmed").length;
  const pending = lineMatches.filter((m) => m.status === "suggested");
  const claimed = r?.rows.find((x) => x.item.id === item.id)?.claimItem.claimed_amount;
  const idx = items.indexOf(item);
  const next = items.slice(idx + 1).concat(items.slice(0, idx)).find((i) => matches.some((m) => m.contract_item_id === i.id && m.status === "suggested")) ?? items[idx + 1];
  const left = items.filter((i) => matches.some((m) => m.contract_item_id === i.id && m.status === "suggested")).length;
  const unlinked = evidence.filter((e) => !matches.some((m) => m.evidence_id === e.id && m.status !== "rejected"));

  return (
    <Page wide>
      <PageHeader
        title="Review evidence"
        sub={`SubPay matched ${lineMatches.length} item${lineMatches.length === 1 ? "" : "s"} to this line. Approve the ones that belong.`}
        right={
          <>
            <select className="input w-auto max-w-xs" value={item.id} onChange={(e) => go(e.target.value)} aria-label="Contract line">
              {items.map((i) => {
                const n = matches.filter((m) => m.contract_item_id === i.id && m.status === "suggested").length;
                return <option key={i.id} value={i.id}>{i.item_code} {i.description}{n ? ` (${n} to review)` : ""}</option>;
              })}
            </select>
            <span className="pill bg-mint px-4 py-2 text-sm text-brand-dark">{approved} of {lineMatches.length} approved</span>
          </>
        }
      />

      {!db.settings.ai_available && (
        <div className="mb-6"><Notice title="AI analysis unavailable">You can continue reviewing evidence manually. Existing suggestions are still shown; new uploads won’t be matched until AI is back.</Notice></div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,4fr)]">
        <div className="space-y-6">
          <section className="card p-6 sm:p-8">
            <p className="eyebrow">Contract line item</p>
            <h2 className="mt-2 text-2xl font-bold sm:text-3xl">{item.item_code} {item.description}</h2>
            <p className="mt-2 text-muted">{item.source_reference}</p>
            <hr className="my-6 border-line" />
            <p className="text-sm text-muted">Claimed this cycle</p>
            <p className="text-4xl font-bold">{claimed != null ? money(claimed) : money(item.amount)}</p>
            <p className="mt-6 text-sm text-muted">Evidence support</p>
            <div className="mt-2"><Progress value={lineMatches.length ? (approved / lineMatches.length) * 100 : 0} /></div>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <p className="font-semibold">{lineMatches.length ? Math.round((approved / lineMatches.length) * 100) : 0}% · {approved} of {lineMatches.length} suggested items approved</p>
              <StateBadge state={completeness(lineMatches)} />
            </div>
            {pending.length > 0 && (
              <div className="mt-6">
                <Notice title={pending.length === 1 ? "One item still needs your call" : `${pending.length} items still need your call`}>
                  Approve or reject {pending.length === 1 ? `the ${(evidence.find((e) => e.id === pending[0].evidence_id)?.title ?? "item").toLowerCase()}` : "them"} to close this line.
                </Notice>
              </div>
            )}
            {item.notice_requirement && (
              <p className="mt-6 flex gap-2 border-t border-line pt-4 text-sm text-amber"><Icon.clock className="h-5 w-5 shrink-0" />Potential requirement — review contract: {item.notice_requirement}</p>
            )}
          </section>

          {next && next.id !== item.id && (
            <button onClick={() => go(next.id)} className="card block w-full p-6 text-left hover:border-sage">
              <p className="font-semibold">Next line: {next.item_code} {next.description}</p>
              <p className="mt-1 text-muted">{left} line{left === 1 ? "" : "s"} left to review in this project</p>
            </button>
          )}
        </div>

        <section>
          <div className="mb-3 flex items-center justify-between">
            <p className="eyebrow">Suggested evidence</p>
            <div className="flex items-center gap-3">
              <span className="hidden text-sm text-muted sm:inline">Sorted by confidence</span>
              <button className="btn-outline btn-sm" onClick={() => setLinking(true)}><Icon.plus className="h-3.5 w-3.5" />Link evidence</button>
            </div>
          </div>

          {lineMatches.length === 0 && (
            <EmptyState title="No evidence linked to this line" body="Evidence appears missing. Upload a photo or docket, or link existing evidence manually." action={<button className="btn-primary" onClick={() => setLinking(true)}>Link evidence</button>} />
          )}

          <ul className="space-y-4">
            {lineMatches.map((m) => {
              const ev = evidence.find((e) => e.id === m.evidence_id) ?? db.evidence.find((e) => e.id === m.evidence_id)!;
              const isPending = m.status === "suggested";
              const low = m.confidence < 0.7;
              return (
                <li key={m.id} className={cx("card p-5 sm:p-6", isPending && low && "border-2 border-amber", isPending && !low && "border-2 border-amber/40")}>
                  <div className="flex gap-4 sm:gap-6">
                    <EvidenceIcon type={ev.evidence_type} className={cx("mt-1 h-8 w-8 shrink-0", isPending && low ? "text-amber" : "text-ink-2")} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="text-lg font-semibold">{ev.title}{ev.evidence_type === "photo" ? ` — ${fmtDateTime(ev.captured_at)}` : `, ${new Date(ev.captured_at).toLocaleDateString("en-AU", { day: "numeric", month: "short" })}`}</p>
                        {m.source === "ai" ? <AiBadge assessment={m.assessment} confidence={m.confidence} /> : <span className="pill bg-surface-2 text-muted">Linked manually</span>}
                      </div>
                      <p className="text-muted">{[ev.metadata.location && `Geotagged ${ev.metadata.location}`, ev.metadata.author].filter(Boolean).join(" · ")}</p>

                      {m.source === "ai" && (
                        <div className="mt-3 rounded-xl bg-surface px-4 py-3 text-sm">
                          <p><span className="font-semibold">AI reasoning:</span> {m.reason}</p>
                          {m.missing_evidence.length > 0 && <p className="mt-1 text-amber"><span className="font-semibold">Possibly missing:</span> {m.missing_evidence.join(", ")}</p>}
                        </div>
                      )}

                      <div className="mt-4 flex flex-wrap items-center gap-2">
                        {isPending ? (
                          <>
                            <button className="btn-primary px-7" onClick={() => decide(m.id, "confirmed")}>Approve</button>
                            <button className="btn-outline" onClick={() => decide(m.id, "rejected")}>Not this line</button>
                            <button className="btn-outline" onClick={() => setChanging(m)}>Change line</button>
                            {low && <span className="text-sm text-amber">Low confidence — check the {m.missing_evidence[0] ?? "details"}</span>}
                          </>
                        ) : (
                          <>
                            <span className="inline-flex items-center gap-2 font-semibold text-brand-dark">
                              <Icon.checkCircle className="h-6 w-6 text-brand" />
                              Approved by {m.confirmed_by === me.id ? "you" : read.actor(db, m.confirmed_by)}
                            </span>
                            <button className="ml-auto text-sm text-muted hover:text-ink-2" onClick={() => decide(m.id, "suggested")}>Undo</button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>

          {rejected.length > 0 && (
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-muted">{rejected.length} rejected suggestion{rejected.length > 1 ? "s" : ""}</summary>
              <ul className="mt-2 space-y-1">
                {rejected.map((m) => (
                  <li key={m.id} className="flex items-center justify-between rounded-lg bg-white px-3 py-2">
                    <span>{db.evidence.find((e) => e.id === m.evidence_id)?.title} — rejected by {read.actor(db, m.confirmed_by)}</span>
                    <button className="link text-xs" onClick={() => decide(m.id, "suggested")}>Reopen</button>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="mt-6">
            <Banner title="AI suggests. You approve. SubPay never submits a claim on its own." body="Every approved link is stored with its source file, time and author." />
          </div>
        </section>
      </div>

      {/* Line overview, dense on desktop */}
      {r && (
        <section className="mt-10">
          <p className="eyebrow mb-3">All lines in {r.claim.name}</p>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {r.rows.map((row) => (
              <button key={row.item.id} onClick={() => go(row.item.id)} className={cx("card flex items-center gap-3 px-4 py-3 text-left hover:border-sage", row.item.id === item.id && "border-brand")}>
                <span className={cx("h-2.5 w-2.5 shrink-0 rounded-full", stateColor(row.state))} />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{row.item.item_code} {row.item.description}</span>
                {row.pending > 0 && <span className="pill bg-amber-bg text-amber">{row.pending}</span>}
              </button>
            ))}
          </div>
        </section>
      )}

      <Dialog open={!!changing} onClose={() => setChanging(null)} title="Move evidence to another line">
        {changing && (
          <ItemPicker items={items.filter((i) => i.id !== changing.contract_item_id)} onPick={(id) => { linkEvidence(changing.evidence_id, id, changing.id); setChanging(null); }} />
        )}
      </Dialog>
      <Dialog open={linking} onClose={() => setLinking(false)} title={`Link evidence to ${item.item_code}`}>
        <EvidencePicker db={db} evidence={evidence} unlinked={unlinked.map((e) => e.id)} exclude={lineMatches.map((m) => m.evidence_id)} onPick={(id) => { linkEvidence(id, item.id); setLinking(false); }} />
      </Dialog>
    </Page>
  );
}

function ItemPicker({ items, onPick }: { items: ContractItem[]; onPick: (id: string) => void }) {
  return (
    <ul className="space-y-2">
      {items.map((i) => (
        <li key={i.id}><button className="w-full rounded-xl border border-line px-4 py-3 text-left font-semibold hover:border-brand" onClick={() => onPick(i.id)}>{i.item_code} {i.description}</button></li>
      ))}
    </ul>
  );
}

function EvidencePicker({ db, evidence, unlinked, exclude, onPick }: { db: Db; evidence: Db["evidence"]; unlinked: string[]; exclude: string[]; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const list = evidence
    .filter((e) => !exclude.includes(e.id))
    .filter((e) => `${e.title} ${e.description}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(unlinked.includes(b.id)) - Number(unlinked.includes(a.id)));
  return (
    <div>
      <input className="input mb-3" placeholder="Search evidence" value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="space-y-2">
        {list.map((e) => (
          <li key={e.id}>
            <button className="flex w-full items-center gap-3 rounded-xl border border-line px-4 py-3 text-left hover:border-brand" onClick={() => onPick(e.id)}>
              <EvidenceIcon type={e.evidence_type} className="h-6 w-6 shrink-0 text-muted" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{e.code} · {e.title}</span>
                <span className="block truncate text-xs text-muted">{e.description}</span>
              </span>
              {unlinked.includes(e.id) && <span className="pill bg-amber-bg text-amber">Unlinked</span>}
            </button>
          </li>
        ))}
        {list.length === 0 && <li className="py-6 text-center text-sm text-muted">No evidence available. Upload some from the Evidence tab.</li>}
      </ul>
      <p className="mt-4 text-xs text-muted">Manual links are recorded as human-confirmed, by {read.actor(db, db.session?.profile_id ?? null)}.</p>
    </div>
  );
}
