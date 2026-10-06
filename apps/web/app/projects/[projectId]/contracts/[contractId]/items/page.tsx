"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useData } from "@/lib/store";
import { read } from "@/lib/api";
import { reviewContractItem, updateContractItem, type ItemPatch, type ReviewAction } from "@/lib/contracts";
import type { ContractItem } from "@/lib/types";
import { Banner, Dialog, ErrorState, Icon, Page, PageHeader, confColor, cx, fmtDate, money, pct } from "@/components/ui";

export default function ContractItemsPage() {
  const db = useData();
  const { projectId, contractId } = useParams<{ projectId: string; contractId: string }>();
  const contract = read.contract(db, contractId);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<ContractItem | null>(null);
  const [onlyDrafts, setOnlyDrafts] = useState(false);

  if (!contract || contract.project_id !== projectId) return <Page><ErrorState title="Contract not found" /></Page>;

  const all = read.contractItems(db, contractId).sort((a, b) => a.item_code.localeCompare(b.item_code, undefined, { numeric: true }));
  const drafts = all.filter((i) => i.review_status === "draft");
  const items = onlyDrafts ? drafts : all;
  const sel = all.find((i) => i.id === selected) ?? null;
  const notices = all.filter((i) => i.notice_requirement && i.review_status !== "rejected");
  const earliest = notices.filter((n) => n.due_date).sort((a, b) => a.due_date!.localeCompare(b.due_date!))[0];

  return (
    <Page wide>
      <PageHeader
        title="Your contract, turned into a claim schedule"
        sub="Every row keeps a clause reference, so you can always see where it came from."
        right={<Link href={`/projects/${projectId}/contracts`} className="btn-outline"><Icon.back className="h-4 w-4" />Contracts</Link>}
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,4fr)]">
        {/* Source document panel */}
        <section className="card hidden p-6 lg:block">
          <p className="eyebrow">Original contract</p>
          <p className="mt-1 truncate text-sm font-semibold">{contract.original_filename}{contract.page_count ? ` · ${contract.page_count} pages` : ""}</p>
          <div className="mt-4 rounded-xl border border-line bg-surface/60 p-6">
            {[90, 75, 98, 68, 92, 50].map((w, i) => <div key={i} className="mb-3 h-2.5 rounded-full bg-surface-2" style={{ width: `${w}%` }} />)}
            {sel ? (
              <div className="my-5 rounded-xl border-2 border-brand bg-mint px-4 py-3">
                <p className="text-sm font-semibold">{sel.source_reference ?? "No clause reference extracted"}</p>
                <p className="text-sm font-semibold">{sel.description}{sel.unit ? `, measured per ${sel.unit}` : ""}</p>
                <p className="text-xs text-brand-dark">matched to line {sel.item_code}</p>
              </div>
            ) : (
              <p className="my-5 rounded-xl border border-dashed border-line px-4 py-3 text-sm text-muted">Select a row to see where it came from.</p>
            )}
            {[92, 70, 85, 55, 92, 72, 48].map((w, i) => <div key={i} className="mb-3 h-2.5 rounded-full bg-surface-2" style={{ width: `${w}%` }} />)}
          </div>
        </section>

        <section className="card p-4 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <p className="eyebrow">Claim schedule SubPay built</p>
            <p className="text-sm text-muted">{all.length} items · {notices.length} notice obligations</p>
          </div>

          <div className="hidden grid-cols-[4rem_1fr_7rem_5.5rem_8.5rem] gap-3 rounded-xl bg-surface-2 px-5 py-3 text-sm font-semibold text-muted md:grid">
            <span>Clause</span><span>Claimable item</span><span className="text-right">Value</span><span className="text-right">AI conf.</span><span className="text-right">Status</span>
          </div>
          <ul className="mt-3 space-y-2.5">
            {items.map((i) => {
              const c = i.extraction_confidence ?? 0;
              const tone = i.review_status === "rejected" ? "border-line opacity-60"
                : i.review_status === "draft" ? (c < 0.7 ? "border-red bg-red-bg" : c < 0.85 ? "border-amber bg-amber-bg" : "border-amber/40")
                : "border-line";
              return (
                <li key={i.id}>
                  <button
                    onClick={() => { setSelected(i.id); setEditing(i); }}
                    onMouseEnter={() => setSelected(i.id)}
                    className={cx("grid w-full grid-cols-[1fr_auto] gap-x-3 gap-y-1 rounded-xl border px-4 py-3.5 text-left transition hover:shadow-sm md:grid-cols-[4rem_1fr_7rem_5.5rem_8.5rem] md:items-center md:px-5", tone)}
                  >
                    <span className="hidden text-muted md:block">{i.source_reference?.match(/Clause ([\d.]+)/)?.[1] ?? "—"}</span>
                    <span className="font-semibold">
                      {i.item_code} {i.description}
                      {i.notice_requirement && <Icon.clock className="ml-1.5 inline h-4 w-4 text-amber" />}
                    </span>
                    <span className="text-right font-semibold">{money(i.amount)}</span>
                    <span className={cx("text-sm font-semibold md:text-right", confColor(i.extraction_confidence))}>
                      <span className="md:hidden text-muted font-normal">AI confidence </span>{pct(i.extraction_confidence)}
                    </span>
                    <span className="text-right"><ItemStatus item={i} /></span>
                  </button>
                </li>
              );
            })}
          </ul>

          {drafts.length > 0 ? (
            <div className="mt-5">
              <Banner
                title={`${drafts.length} item${drafts.length > 1 ? "s" : ""} need a human check before you claim on them`}
                body={drafts.find((d) => d.conditions)?.conditions ?? "AI-extracted values stay drafts until you confirm them."}
                action={<button className="btn-primary shrink-0 px-7 py-3" onClick={() => (onlyDrafts ? setEditing(drafts[0]) : setOnlyDrafts(true))}>{onlyDrafts ? "Start checking" : `Check ${drafts.length} items`}</button>}
              />
            </div>
          ) : (
            <p className="mt-5 flex items-center gap-2 rounded-xl bg-mint px-5 py-4 font-semibold text-brand-dark"><Icon.checkCircle className="h-6 w-6 text-brand" />Every line has been reviewed by a person.</p>
          )}
          {onlyDrafts && <button className="mt-3 text-sm link" onClick={() => setOnlyDrafts(false)}>Show all items</button>}
        </section>
      </div>

      {notices.length > 0 && (
        <p className="mt-6">
          Also created: a deadline register with {notices.length} notice obligation{notices.length > 1 ? "s" : ""}
          {earliest ? <>, the earliest closing <strong>{fmtDate(earliest.due_date)}</strong></> : null}. <span className="text-muted">Potential requirements — always check against the contract.</span>
        </p>
      )}

      <Dialog open={!!editing} onClose={() => setEditing(null)} title={editing ? `${editing.item_code} ${editing.description}` : ""}>
        {editing && <ItemEditor key={editing.id} item={all.find((x) => x.id === editing.id)!} onDone={() => setEditing(null)} />}
      </Dialog>
    </Page>
  );
}

function ItemStatus({ item }: { item: ContractItem }) {
  if (item.review_status === "confirmed")
    return <span className="inline-flex items-center gap-1 text-xs font-semibold text-brand-dark"><Icon.checkCircle className="h-4 w-4 text-brand" />{item.edited_by_human ? "Edited · " : ""}Confirmed</span>;
  if (item.review_status === "rejected") return <span className="text-xs font-semibold text-muted">Rejected</span>;
  return <span className="inline-flex items-center gap-1 text-xs font-semibold text-amber"><Icon.spark className="h-3.5 w-3.5" />AI draft</span>;
}

const FIELDS: [keyof ContractItem, string, "text" | "number" | "date"][] = [
  ["description", "Description", "text"],
  ["quantity", "Quantity", "number"],
  ["unit", "Unit", "text"],
  ["rate", "Rate ($)", "number"],
  ["amount", "Amount ($)", "number"],
  ["conditions", "Conditions", "text"],
  ["notice_requirement", "Notice requirement", "text"],
  ["due_date", "Notice due date", "date"],
];

function ItemEditor({ item, onDone }: { item: ContractItem; onDone: () => void }) {
  const db = useData();
  const [f, setF] = useState(() => Object.fromEntries(FIELDS.map(([k]) => [k, item[k] == null ? "" : String(item[k])])));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function save() {
    const patch = Object.fromEntries(
      FIELDS.map(([k, , t]) => [k, f[k] === "" ? null : t === "number" ? Number(f[k]) : f[k]]),
    );
    if (!patch.description) patch.description = item.description;
    return updateContractItem(item.id, patch as ItemPatch);
  }

  /** Run the steps in order; close the dialog only if they all succeed. */
  async function run(close: boolean, ...steps: (() => Promise<void> | void)[]) {
    setError("");
    setBusy(true);
    try {
      for (const step of steps) await step();
      if (close) onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const review = (status: ReviewAction) => () => reviewContractItem(item.id, status);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="pill bg-surface-2 text-muted"><Icon.spark className="h-3 w-3" />AI extracted · {pct(item.extraction_confidence)} confidence</span>
        {item.edited_by_human && <span className="pill bg-amber-bg text-amber">Edited by a person</span>}
        {item.review_status === "confirmed" && <span className="pill bg-mint text-brand-dark">Confirmed by {read.actor(db, item.reviewed_by)}</span>}
        {item.review_status === "rejected" && <span className="pill bg-red-bg text-red">Rejected</span>}
      </div>
      <p className="mb-4 text-sm text-muted">Source: {item.source_reference ?? "not found in contract"}. Blank fields were not found in the contract — SubPay leaves them empty rather than guessing.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map(([k, label, t]) => (
          <label key={k} className={cx("block", (k === "description" || k === "conditions" || k === "notice_requirement") && "sm:col-span-2")}>
            <span className="label">{label}</span>
            <input className="input" type={t} step="any" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} placeholder="Not found" />
          </label>
        ))}
      </div>
      {error && <p className="mt-4 rounded-xl bg-red-bg px-4 py-3 text-sm text-red" role="alert">{error}</p>}
      <div className="mt-6 flex flex-wrap justify-end gap-2">
        {item.review_status !== "rejected" && <button className="btn-danger" disabled={busy} onClick={() => void run(true, review("rejected"))}>Reject item</button>}
        {item.review_status !== "draft" && <button className="btn-outline" disabled={busy} onClick={() => void run(false, review("draft"))}>Back to draft</button>}
        <button className="btn-outline" disabled={busy} onClick={() => void run(true, save)}>Save edits</button>
        <button className="btn-primary" disabled={busy} onClick={() => void run(true, save, review("confirmed"))}>Save & confirm</button>
      </div>
    </div>
  );
}
