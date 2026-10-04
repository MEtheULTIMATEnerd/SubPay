"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { useData } from "@/lib/store";
import { read, setVariationStatus } from "@/lib/api";
import { LIVE } from "@/lib/env";
import { getEvidenceDownloadUrl, previewFailed, previewOf, rerunMatching, setEvidenceArchived, updateEvidence, uploadEvidence } from "@/lib/evidence";
import { localDateTime, thumbnail, typeFromMime } from "@/lib/thumbnail";
import type { Db, Evidence, EvidenceType } from "@/lib/types";
import {
  AiBadge, Dialog, EmptyState, ErrorState, EvidenceIcon, Field, HumanStatus, Icon, Notice, Page, PageHeader, ProcessingBadge, cx, fmtDateTime, money,
} from "@/components/ui";

const TYPES: EvidenceType[] = ["photo", "document", "docket", "message", "other"];
const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
const ACCEPT = "image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif,.pdf,.docx,.xlsx,.txt,.csv";

export default function EvidencePage() {
  const db = useData();
  const { projectId } = useParams<{ projectId: string }>();
  const [q, setQ] = useState("");
  const [type, setType] = useState<EvidenceType | "">("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [archived, setArchived] = useState(false);
  const [view, setView] = useState<"grid" | "list">("grid");
  const [openId, setOpenId] = useState<string | null>(null);
  const [pending, setPending] = useState<File[] | null>(null);
  const [drag, setDrag] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const all = read.evidence(db, projectId);
  const matches = read.matches(db, projectId);
  const variations = read.variations(db, projectId).filter((v) => v.status === "flagged");
  const list = all
    .filter((e) => e.archived === archived)
    .filter((e) => !type || e.evidence_type === type)
    .filter((e) => !from || e.captured_at.slice(0, 10) >= from)
    .filter((e) => !to || e.captured_at.slice(0, 10) <= to)
    .filter((e) => `${e.code} ${e.title} ${e.description} ${e.original_filename ?? ""} ${e.metadata.location ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()))
    .sort((a, b) => b.captured_at.localeCompare(a.captured_at));
  const open = all.find((e) => e.id === openId);

  return (
    <Page wide>
      <PageHeader
        title="Evidence"
        sub="Photos, dockets, messages and files — saved with time, place and author."
        right={
          <>
            <Link href={`/projects/${projectId}/evidence/capture`} className="btn-dark"><Icon.camera className="h-4 w-4" />Capture on site</Link>
            <button className="btn-primary" onClick={() => picker.current?.click()}><Icon.upload className="h-4 w-4" />Upload</button>
            <input ref={picker} type="file" multiple hidden accept={ACCEPT} onChange={(e) => { if (e.target.files?.length) setPending([...e.target.files]); e.target.value = ""; }} />
          </>
        }
      />

      {!db.settings.ai_available && (
        <div className="mb-5"><Notice title="AI analysis unavailable">You can continue reviewing evidence manually — link evidence to contract items from the Review tab.</Notice></div>
      )}

      {variations.length > 0 && (
        <div className="mb-6 space-y-2">
          {variations.map((v) => (
            <div key={v.id} className="flex flex-col gap-3 rounded-2xl border border-red/30 bg-white p-4 sm:flex-row sm:items-center">
              <Icon.flag className="h-6 w-6 shrink-0 text-red" />
              <div className="flex-1">
                <p className="font-semibold">{v.code} Potential variation — {v.title}</p>
                <p className="text-sm text-muted">{v.reason} <span className="text-xs">(AI flag, {Math.round(v.confidence * 100)}% — review required, not an approved variation)</span></p>
              </div>
              {v.estimated_amount != null && <span className="font-semibold text-red">{money(v.estimated_amount)}</span>}
              <div className="flex gap-2">
                <button className="btn-outline btn-sm" onClick={() => setVariationStatus(v.id, "acknowledged")}>Acknowledge</button>
                <button className="btn-outline btn-sm" onClick={() => setVariationStatus(v.id, "dismissed")}>Dismiss</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (e.dataTransfer.files.length) setPending([...e.dataTransfer.files]); }}
        className={cx("mb-6 hidden items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-6 text-sm md:flex", drag ? "border-brand bg-mint" : "border-line text-muted")}
      >
        <Icon.upload className="h-5 w-5" /> Drag photos, dockets or documents here
      </div>

      {/* filters */}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_10rem_9.5rem_9.5rem_auto]">
        <div className="relative">
          <Icon.search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input className="input pl-9" placeholder="Search evidence" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <select className="input" value={type} onChange={(e) => setType(e.target.value as EvidenceType | "")} aria-label="Evidence type">
          <option value="">All types</option>
          {TYPES.map((t) => <option key={t} value={t}>{cap(t)}</option>)}
        </select>
        <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Captured from" />
        <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Captured to" />
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />Archived</label>
          <div className="ml-auto inline-flex rounded-full border border-line bg-white p-1">
            <button onClick={() => setView("grid")} className={cx("rounded-full p-1.5", view === "grid" && "bg-ink text-white")} aria-label="Grid view"><Icon.grid className="h-4 w-4" /></button>
            <button onClick={() => setView("list")} className={cx("rounded-full p-1.5", view === "list" && "bg-ink text-white")} aria-label="List view"><Icon.list className="h-4 w-4" /></button>
          </div>
        </div>
      </div>

      {list.length === 0 ? (
        <EmptyState icon={<Icon.camera className="h-10 w-10" />} title={all.length ? "No evidence matches these filters" : "No evidence yet"} body="Upload site photos, delivery dockets, emails or timesheets." />
      ) : view === "grid" ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {list.map((e) => (
            <button key={e.id} onClick={() => setOpenId(e.id)} className="card overflow-hidden text-left transition hover:border-sage hover:shadow-sm">
              <Preview e={e} className="h-40" />
              <div className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold">{e.title}</p>
                  <ProcessingBadge status={e.processing_status} />
                </div>
                <p className="mt-0.5 text-sm text-muted">{fmtDateTime(e.captured_at)}{e.metadata.location ? ` · ${e.metadata.location}` : ""}</p>
                <LinkSummary db={db} e={e} matches={matches} />
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="card divide-y divide-line">
          {list.map((e) => (
            <button key={e.id} onClick={() => setOpenId(e.id)} className="flex w-full items-center gap-4 px-5 py-3.5 text-left hover:bg-surface">
              <EvidenceIcon type={e.evidence_type} className="h-6 w-6 shrink-0 text-muted" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{e.code} · {e.title}</p>
                <p className="truncate text-sm text-muted">{e.description}</p>
              </div>
              <span className="hidden text-sm text-muted md:block">{fmtDateTime(e.captured_at)}</span>
              <ProcessingBadge status={e.processing_status} />
            </button>
          ))}
        </div>
      )}

      <Dialog open={!!pending} onClose={() => setPending(null)} title={`Add ${pending?.length === 1 ? "evidence" : `${pending?.length} files`}`}>
        {pending && <UploadForm files={pending} projectId={projectId} onDone={() => setPending(null)} />}
      </Dialog>
      <Dialog open={!!open} onClose={() => setOpenId(null)} title={open ? `${open.code} · ${open.title}` : ""}>
        {open && <EvidenceDetail db={db} e={open} />}
      </Dialog>
    </Page>
  );
}

function Preview({ e, className }: { e: Evidence; className?: string }) {
  const src = previewOf(e);
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={e.title} className={cx("w-full object-cover", className)} onError={() => previewFailed(e.project_id)} />
  ) : (
    <div className={cx("flex w-full items-center justify-center bg-surface-2 text-sage", className)}>
      <EvidenceIcon type={e.evidence_type} className="h-12 w-12" />
    </div>
  );
}

function LinkSummary({ db, e, matches }: { db: Db; e: Evidence; matches: Db["evidence_matches"] }) {
  const m = matches.filter((x) => x.evidence_id === e.id && x.status !== "rejected");
  if (e.processing_status === "failed") return <p className="mt-2 text-xs text-red">AI analysis unavailable — link manually</p>;
  if (!m.length) return <p className="mt-2 text-xs text-muted">Not linked to a contract item</p>;
  const items = read.projectItems(db, e.project_id);
  return (
    <p className="mt-2 text-xs">
      {m.map((x) => (
        <span key={x.id} className={cx("mr-1 inline-block", x.status === "confirmed" ? "text-brand-dark" : "text-amber")}>
          {x.status === "confirmed" ? "✓" : "AI?"} {items.find((i) => i.id === x.contract_item_id)?.item_code}
        </span>
      ))}
    </p>
  );
}

function UploadForm({ files, projectId, onDone }: { files: File[]; projectId: string; onDone: () => void }) {
  const first = files[0];
  const [f, setF] = useState(() => ({
    title: files.length === 1 ? first.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ") : "",
    description: "",
    evidence_type: typeFromMime(first.type) as EvidenceType,
    captured_at: localDateTime(new Date(first.lastModified || Date.now())),
    location: "",
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (files.length === 1 && Number.isNaN(new Date(f.captured_at).getTime())) throw new Error("Enter the date and time this was captured");
      for (const file of files) {
        await uploadEvidence(projectId, {
          file, title: files.length === 1 ? f.title : file.name, description: f.description,
          evidence_type: files.length === 1 ? f.evidence_type : (typeFromMime(file.type) as EvidenceType),
          captured_at: new Date(files.length === 1 ? f.captured_at : file.lastModified || Date.now()).toISOString(),
          location: f.location || null, thumbnail: await thumbnail(file),
        });
      }
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <ErrorState title={error} />}
      <ul className="space-y-1 text-sm text-muted">
        {files.map((x) => <li key={x.name} className="truncate">📎 {x.name} · {(x.size / 1024).toFixed(0)} KB</li>)}
      </ul>
      {files.length === 1 && (
        <>
          <Field label="Title"><input className="input" required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Type">
              <select className="input" value={f.evidence_type} onChange={(e) => setF({ ...f, evidence_type: e.target.value as EvidenceType })}>
                {TYPES.map((t) => <option key={t} value={t}>{cap(t)}</option>)}
              </select>
            </Field>
            <Field label="Captured"><input className="input" type="datetime-local" value={f.captured_at} onChange={(e) => setF({ ...f, captured_at: e.target.value })} /></Field>
          </div>
        </>
      )}
      <Field label="What does this show?" hint="Helps SubPay suggest the right contract item, e.g. “Edge beam formwork level 3 grid C5”.">
        <textarea className="input min-h-20" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
      </Field>
      <Field label="Location (optional)"><input className="input" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="Grid C4, Level 3" /></Field>
      {busy && <div className="h-1.5 overflow-hidden rounded-full bg-surface-2"><div className="h-full w-2/3 animate-pulse rounded-full bg-brand" /></div>}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-outline" onClick={onDone}>Cancel</button>
        <button className="btn-primary" disabled={busy}>{busy ? "Uploading…" : "Upload & match"}</button>
      </div>
    </form>
  );
}

function EvidenceDetail({ db, e }: { db: Db; e: Evidence }) {
  const [edit, setEdit] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [f, setF] = useState({ title: e.title, description: e.description, evidence_type: e.evidence_type, location: e.metadata.location ?? "" });

  /** Run one action; show what went wrong instead of failing silently. */
  async function run(action: () => Promise<void> | void) {
    setError("");
    setBusy(true);
    try {
      await action();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const save = () => run(async () => {
    await updateEvidence(e.id, { ...f, location: f.location.trim() || null });
    setEdit(false);
  });
  const openFile = () => run(async () => {
    const url = await getEvidenceDownloadUrl(e.id);
    if (!url) throw new Error("The file is not available right now.");
    window.location.assign(url); // a short-lived link that downloads the file
  });
  const items = read.projectItems(db, e.project_id);
  const m = read.matches(db, e.project_id).filter((x) => x.evidence_id === e.id);

  return (
    <div className="space-y-5">
      <Preview e={e} className="h-56 rounded-xl" />
      {error && <ErrorState title={error} />}
      {edit ? (
        <div className="space-y-3">
          <Field label="Title"><input className="input" value={f.title} onChange={(x) => setF({ ...f, title: x.target.value })} /></Field>
          <Field label="Description"><textarea className="input" value={f.description} onChange={(x) => setF({ ...f, description: x.target.value })} /></Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Type">
              <select className="input" value={f.evidence_type} onChange={(x) => setF({ ...f, evidence_type: x.target.value as EvidenceType })}>
                {TYPES.map((t) => <option key={t} value={t}>{cap(t)}</option>)}
              </select>
            </Field>
            <Field label="Location"><input className="input" value={f.location} onChange={(x) => setF({ ...f, location: x.target.value })} /></Field>
          </div>
          <div className="flex justify-end gap-2">
            <button className="btn-outline" disabled={busy} onClick={() => { setError(""); setEdit(false); }}>Cancel</button>
            <button className="btn-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save"}</button>
          </div>
        </div>
      ) : (
        <dl className="grid grid-cols-[7rem_1fr] gap-y-2 text-sm">
          <dt className="text-muted">Description</dt><dd>{e.description || "—"}</dd>
          <dt className="text-muted">Type</dt><dd>{cap(e.evidence_type)}</dd>
          <dt className="text-muted">Captured</dt><dd>{fmtDateTime(e.captured_at)}</dd>
          <dt className="text-muted">Location</dt><dd>{e.metadata.location ?? "—"}</dd>
          <dt className="text-muted">Source</dt><dd>{e.metadata.author ?? read.actor(db, e.uploaded_by)} · {(e.metadata.source ?? "upload").replace("_", " ")}</dd>
          <dt className="text-muted">File</dt><dd className="break-all">{e.original_filename ?? "Written note, no file"}</dd>
          <dt className="text-muted">AI status</dt><dd><ProcessingBadge status={e.processing_status} /></dd>
        </dl>
      )}

      <div>
        <p className="eyebrow mb-2">Contract links</p>
        {m.length === 0 && <p className="text-sm text-muted">No links yet.</p>}
        <ul className="space-y-2">
          {m.map((x) => {
            const it = items.find((i) => i.id === x.contract_item_id);
            return (
              <li key={x.id} className="rounded-xl border border-line px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-semibold">{it?.item_code} {it?.description}</span>
                  {x.source === "ai" ? <AiBadge assessment={x.assessment} confidence={x.confidence} /> : <span className="pill bg-surface-2 text-muted">Linked manually</span>}
                </div>
                <div className="mt-1"><HumanStatus status={x.status} by={read.actor(db, x.confirmed_by)} /></div>
              </li>
            );
          })}
        </ul>
        <Link href={`/projects/${e.project_id}/review?evidence=${e.id}`} className="mt-3 inline-block text-sm link">Review links</Link>
      </div>

      {!edit && (
        <div className="flex flex-wrap justify-end gap-2 border-t border-line pt-4">
          {LIVE && e.storage_path && <button className="btn-outline btn-sm" disabled={busy} onClick={openFile}>Download file</button>}
          {db.settings.ai_available && <button className="btn-outline btn-sm" disabled={busy || e.processing_status === "processing"} onClick={() => run(() => rerunMatching(e.id))}>Re-run AI matching</button>}
          <button className="btn-outline btn-sm" disabled={busy} onClick={() => setEdit(true)}>Edit details</button>
          <button className="btn-outline btn-sm" disabled={busy} onClick={() => run(() => setEvidenceArchived(e.id, !e.archived))}>{e.archived ? "Restore" : "Archive"}</button>
        </div>
      )}
    </div>
  );
}
