"use client";
// Site-worker capture flow: photo → which item is this? → add to claim. Built for phones.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useData } from "@/lib/store";
import { linkEvidence, read } from "@/lib/api";
import { matchEvidence } from "@/lib/ai";
import { uploadEvidence } from "@/lib/evidence";
import { thumbnail } from "@/lib/thumbnail";
import { ErrorState, Icon, ProgressBar, cx } from "@/components/ui";

export default function CapturePage() {
  const db = useData();
  const router = useRouter();
  const { projectId } = useParams<{ projectId: string }>();
  const project = read.project(db, projectId)!;
  const claim = read.claims(db, projectId).at(-1);
  const items = read.projectItems(db, projectId).filter((i) => i.review_status === "confirmed");
  const cam = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [thumb, setThumb] = useState<string | null>(null);
  const [takenAt, setTakenAt] = useState(new Date());
  const [note, setNote] = useState("");
  const [location, setLocation] = useState("");
  const [choice, setChoice] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sent, setSent] = useState(0); // share of the photo uploaded so far, 0 to 1

  // Live suggestions from the (mock) AI as the worker types what the photo shows.
  const suggested = db.settings.ai_available && note.trim()
    ? matchEvidence({ id: "draft", title: "", description: `${note} ${location}`, evidence_type: "photo" }, items).matches
    : [];
  const options = showAll
    ? items
    : suggested.length
      ? suggested.map((s) => items.find((i) => i.id === s.contract_item_id)!)
      : items.slice(0, 3);
  const best = suggested[0]?.contract_item_id;

  async function pick(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setTakenAt(new Date(f.lastModified || Date.now()));
    setThumb(await thumbnail(f));
  }

  async function add() {
    if (saving) return;
    setError("");
    setSaving(true);
    setSent(0);
    try {
      const id = await uploadEvidence(projectId, {
        file, title: file ? "Site photo" : "Site note", description: note, evidence_type: file ? "photo" : "message", captured_at: takenAt.toISOString(),
        location: location || null, thumbnail: thumb, source: "mobile_upload",
      }, { autoMatch: !choice, onProgress: setSent });
      if (choice) linkEvidence(id, choice);
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  function reset() {
    setFile(null); setThumb(null); setTakenAt(new Date()); setNote(""); setChoice(null); setShowAll(false); setDone(false); setError("");
  }

  return (
    <div className="mx-auto max-w-md bg-white sm:my-6 sm:overflow-hidden sm:rounded-[2rem] sm:border-[10px] sm:border-ink">
      <div className="flex items-center justify-between bg-mint px-5 py-4">
        <span className="flex items-center gap-2.5 text-lg font-semibold"><Icon.checkCircle className="h-6 w-6 text-brand" />{project.name}</span>
        <span className="text-sm text-brand-dark">{claim ? `Claim #${claim.number}` : ""}</span>
      </div>

      <div className="px-5 pb-6 pt-5">
        {done ? (
          <div className="py-10 text-center">
            <Icon.checkCircle className="mx-auto h-16 w-16 text-brand" />
            <p className="mt-4 text-2xl font-bold">Saved to the claim</p>
            <p className="mt-1 text-muted">{choice ? "Linked and confirmed by you." : "SubPay will suggest a contract item for you to confirm."}</p>
            <div className="mt-8 space-y-3">
              <button className="btn-dark w-full py-4 text-base" onClick={reset}>Take another photo</button>
              <button className="btn-outline w-full py-3" onClick={() => router.push(`/projects/${projectId}/evidence`)}>Done</button>
            </div>
          </div>
        ) : (
          <>
            <button onClick={() => cam.current?.click()} className="block w-full overflow-hidden rounded-xl bg-surface-2 text-left">
              {thumb ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={thumb} alt="Captured" className="h-56 w-full object-cover" />
              ) : (
                <span className="flex h-56 flex-col items-center justify-center gap-2 text-sage">
                  <Icon.camera className="h-14 w-14" />
                  <span className="text-sm font-semibold text-muted">{file ? file.name : "Tap to take a photo"}</span>
                </span>
              )}
              <span className="block bg-ink px-4 py-3 text-white">
                <span className="block font-semibold">
                  {file ? `Photo taken ${takenAt.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" })}, ${takenAt.toLocaleDateString("en-AU", { day: "numeric", month: "short" })}` : "No photo yet"}
                </span>
                <span className="block text-sm text-sage">{location || "Add a location below"} · saved with time and location</span>
              </span>
            </button>
            <input ref={cam} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pick(e.target.files?.[0])} />

            <div className="mt-4 grid grid-cols-2 gap-2">
              <input className="input" placeholder="What is it? e.g. edge beams" value={note} onChange={(e) => setNote(e.target.value)} />
              <input className="input" placeholder="Grid C4, Level 3" value={location} onChange={(e) => setLocation(e.target.value)} />
            </div>

            <h1 className="mt-6 text-2xl font-bold">Which item is this?</h1>
            <p className="text-muted">Tap one. You can change it later.</p>
            {!db.settings.ai_available && <p className="mt-2 text-sm text-amber">AI suggestions unavailable — pick the item yourself.</p>}

            <ul className="mt-4 space-y-3">
              {options.map((i) => {
                const on = choice === i.id;
                return (
                  <li key={i.id}>
                    <button
                      onClick={() => setChoice(on ? null : i.id)}
                      className={cx("flex w-full items-center justify-between rounded-xl border-2 px-5 py-4 text-left text-lg font-semibold transition",
                        on ? "border-brand bg-brand text-white" : "border-line bg-surface")}
                    >
                      <span>
                        {i.item_code} {i.description}
                        {i.id === best && <span className={cx("block text-sm font-normal", on ? "text-white/90" : "text-brand-dark")}>Best match (AI suggestion)</span>}
                      </span>
                      {on && <Icon.checkCircle className="h-8 w-8 shrink-0 text-white [&_path]:stroke-brand" />}
                    </button>
                  </li>
                );
              })}
            </ul>
            {!showAll && items.length > options.length && (
              <button className="mt-4 font-semibold text-brand-dark" onClick={() => setShowAll(true)}>Something else</button>
            )}
            {items.length === 0 && <p className="mt-3 text-sm text-muted">No confirmed contract items yet. <Link href={`/projects/${projectId}/contracts`} className="link">Upload a contract</Link></p>}

            {error && <div className="mt-4"><ErrorState title={error} /></div>}
            <button className="btn-dark mt-6 w-full py-5 text-lg" disabled={saving || (!file && !note.trim())} onClick={add}>
              {saving ? (file ? `Saving… ${Math.round(sent * 100)}%` : "Saving…") : choice ? "Add to claim" : "Save, let SubPay suggest"}
            </button>
            {saving && file && <ProgressBar value={sent} label="Upload progress" className="mt-3" />}
            <p className="mt-4 text-center text-sm text-muted">Three taps. Works in gloves, in direct sun.</p>
          </>
        )}
      </div>
    </div>
  );
}
