"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useData } from "@/lib/store";
import { read, readiness } from "@/lib/api";
import { LIVE } from "@/lib/env";
import { setProjectStatus, updateProject } from "@/lib/projects";
import type { Project } from "@/lib/types";
import { ProjectForm } from "@/components/projects";
import { Dialog, ErrorState, Icon, Page, PageHeader, Progress, cx, fmtDate, fmtDateTime } from "@/components/ui";

export default function ProjectOverview() {
  const db = useData();
  const { projectId } = useParams<{ projectId: string }>();
  const p = read.project(db, projectId)!;
  const [editing, setEditing] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function changeStatus(status: Project["status"]) {
    setError("");
    setBusy(true);
    try {
      await setProjectStatus(p.id, status);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setArchiving(false);
    }
  }

  const base = `/projects/${p.id}`;
  const contracts = read.contracts(db, p.id);
  const items = read.projectItems(db, p.id);
  const evidence = read.evidence(db, p.id).filter((e) => !e.archived);
  const matches = read.matches(db, p.id);
  const claim = read.claims(db, p.id).at(-1);
  const r = !LIVE && claim ? readiness(db, claim.id) : null;
  const confirmedItems = items.filter((i) => i.review_status === "confirmed").length;

  // The MVP journey, with live status for each step.
  const steps: [string, string, boolean, string][] = [
    ["Upload contract", `${contracts.length} uploaded`, contracts.some((c) => c.processing_status === "ready"), `${base}/contracts`],
    ["Review claim schedule", `${confirmedItems} of ${items.length} items confirmed`, items.length > 0 && confirmedItems === items.length, contracts[0] ? `${base}/contracts/${contracts[0].id}/items` : `${base}/contracts`],
    ["Capture evidence", `${evidence.length} records`, evidence.length > 0, `${base}/evidence`],
    ["Confirm AI matches", `${matches.filter((m) => m.status === "suggested").length} awaiting review`, matches.length > 0 && !matches.some((m) => m.status === "suggested"), `${base}/review`],
    ["Check claim readiness", LIVE ? "Not available yet" : r ? `${r.coverage}% evidence support` : "No claim yet", !!r && r.rows.length > 0 && r.counts.strong === r.rows.length && r.pendingMatches === 0, claim ? `${base}/claims/${claim.id}` : `${base}/claims`],
    ["Export evidence package", claim?.status === "exported" ? "Exported" : "Not yet exported", claim?.status === "exported", claim ? `${base}/claims/${claim.id}/export` : `${base}/claims`],
  ];

  return (
    <Page wide>
      <PageHeader
        title="Overview"
        sub={`${p.site_address || "No site address"} · ${fmtDate(p.start_date)} – ${fmtDate(p.end_date)}`}
        right={
          <>
            <button className="btn-outline" onClick={() => setEditing(true)}>Edit project</button>
            {p.status === "active"
              ? <button className="btn-outline" onClick={() => setArchiving(true)}>Archive</button>
              : <button className="btn-primary" disabled={busy} onClick={() => void changeStatus("active")}>Restore project</button>}
          </>
        }
      />
      {error && <div className="mb-6"><ErrorState title={error} /></div>}

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="card p-6 lg:col-span-2">
          <p className="eyebrow mb-4">Claim journey</p>
          <ol className="space-y-2">
            {steps.map(([title, sub, done, href], i) => (
              <li key={title}>
                <Link href={href} className="flex items-center gap-4 rounded-xl border border-line px-4 py-3 hover:border-sage">
                  {done ? <Icon.checkCircle className="h-7 w-7 shrink-0 text-brand" /> : (
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-semibold text-white">{i + 1}</span>
                  )}
                  <span className="flex-1">
                    <span className="block font-semibold">{title}</span>
                    <span className="block text-sm text-muted">{sub}</span>
                  </span>
                  <Icon.arrow className="h-4 w-4 text-sage" />
                </Link>
              </li>
            ))}
          </ol>
        </section>

        <div className="space-y-6">
          {r && (
            <Link href={`${base}/claims/${r.claim.id}`} className="block rounded-2xl bg-ink p-6 text-white">
              <p className="text-sm text-sage">{r.claim.name} · Evidence support coverage</p>
              <p className="mt-1 text-5xl font-bold">{r.coverage}%</p>
              <div className="mt-4"><Progress value={r.coverage} dark /></div>
              <p className="mt-3 text-sm text-sage">{r.counts.strong} strong · {r.counts.partial} partial · {r.counts.weak} weak · {r.counts.missing} missing</p>
            </Link>
          )}
          <section className="card p-6">
            <p className="eyebrow mb-3">Recent activity</p>
            <ul className="space-y-3 text-sm">
              {read.audit(db, p.id).slice(0, 5).map((a) => (
                <li key={a.id} className="flex gap-3">
                  <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", a.actor_id ? "bg-brand" : "bg-sage")} />
                  <span>
                    <span className="font-medium">{read.actor(db, a.actor_id)}</span> {a.action.replace(/[._]/g, " ")}
                    <span className="block text-xs text-muted">{fmtDateTime(a.created_at)}</span>
                  </span>
                </li>
              ))}
            </ul>
            <Link href={`${base}/audit`} className="mt-4 inline-block text-sm link">Full audit trail</Link>
          </section>
        </div>
      </div>

      <Dialog open={editing} onClose={() => setEditing(false)} title="Edit project">
        <ProjectForm initial={p} submitLabel="Save changes" onCancel={() => setEditing(false)} onSubmit={async (f) => { await updateProject(p.id, f); setEditing(false); }} />
      </Dialog>
      <Dialog open={archiving} onClose={() => setArchiving(false)} title="Archive project?">
        <p className="text-sm text-muted">Archived projects are hidden from your dashboard. All contracts, evidence and audit history are kept, and you can restore it any time.</p>
        <div className="mt-6 flex justify-end gap-2">
          <button className="btn-outline" onClick={() => setArchiving(false)}>Cancel</button>
          <button className="btn-dark" disabled={busy} onClick={() => void changeStatus("archived")}>{busy ? "Archiving…" : "Archive project"}</button>
        </div>
      </Dialog>
    </Page>
  );
}
