"use client";
import Link from "next/link";
import { useState } from "react";
import type { Db, Project } from "@/lib/types";
import { read, readiness } from "@/lib/api";
import { LIVE } from "@/lib/env";
import { Icon, Progress, cx, fmtDate } from "./ui";

export function ProjectCard({ db, p }: { db: Db; p: Project }) {
  const claim = read.claims(db, p.id).at(-1);
  const r = !LIVE && claim ? readiness(db, claim.id) : null;
  return (
    <Link href={`/projects/${p.id}`} className="card group flex flex-col p-6 transition hover:border-sage hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-lg font-semibold group-hover:text-brand-dark">{p.name}</p>
          <p className="truncate text-sm text-muted">{p.client_name} · {p.site_address}</p>
        </div>
        <StatusPill status={p.status} />
      </div>
      {r ? (
        <div className="mt-6">
          <div className="mb-2 flex justify-between text-sm">
            <span className="text-muted">{r.claim.name}</span>
            <span className="font-semibold">{r.coverage}% evidence support</span>
          </div>
          <Progress value={r.coverage} />
          <p className="mt-2 text-xs text-muted">
            {r.reviewed} of {r.rows.length} lines reviewed · {r.pendingMatches} AI suggestions waiting · due {fmtDate(r.claim.due_date)}
          </p>
        </div>
      ) : (
        <p className="mt-6 text-sm text-muted">No claim started yet.</p>
      )}
    </Link>
  );
}

export function StatusPill({ status }: { status: Project["status"] }) {
  return <span className={cx("pill", status === "active" ? "bg-mint text-brand-dark" : "bg-surface-2 text-muted")}>{status === "active" ? "Active" : "Archived"}</span>;
}

type Form = Pick<Project, "name" | "client_name" | "site_address" | "start_date" | "end_date">;
export function ProjectForm({ initial, submitLabel, onSubmit, onCancel }: {
  initial?: Partial<Form>; submitLabel: string; onSubmit: (f: Form) => void | Promise<void>; onCancel?: () => void;
}) {
  const [f, setF] = useState<Form>({
    name: initial?.name ?? "", client_name: initial?.client_name ?? "", site_address: initial?.site_address ?? "",
    start_date: initial?.start_date ?? null, end_date: initial?.end_date ?? null,
  });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value || (k.endsWith("date") ? null : "") });
  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setError("");
        setPending(true);
        try {
          await onSubmit(f);
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setPending(false);
        }
      }}
    >
      {error && <p className="rounded-xl bg-red-bg px-4 py-3 text-sm text-red" role="alert">{error}</p>}
      <label className="block"><span className="label">Project name</span><input className="input" required value={f.name} onChange={set("name")} placeholder="Hume St Tower" /></label>
      <label className="block"><span className="label">Head contractor / client</span><input className="input" required value={f.client_name} onChange={set("client_name")} placeholder="Bellrock Construction" /></label>
      <label className="block"><span className="label">Site address</span><input className="input" value={f.site_address} onChange={set("site_address")} /></label>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block"><span className="label">Start date</span><input className="input" type="date" value={f.start_date ?? ""} onChange={set("start_date")} /></label>
        <label className="block"><span className="label">End date</span><input className="input" type="date" value={f.end_date ?? ""} onChange={set("end_date")} /></label>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        {onCancel && <button type="button" className="btn-outline" onClick={onCancel} disabled={pending}>Cancel</button>}
        <button className="btn-dark" disabled={pending}>{pending ? "Saving…" : submitLabel}</button>
      </div>
    </form>
  );
}

export function NewProjectButton() {
  return <Link href="/projects/new" className="btn-primary"><Icon.plus className="h-4 w-4" />New project</Link>;
}
