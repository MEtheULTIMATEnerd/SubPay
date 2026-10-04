"use client";
// Shared UI foundation: page layout, states, badges, dialog, icons, formatters.
import { useEffect, useRef, type ReactNode } from "react";
import type { Assessment, Completeness, MatchStatus, ProcessingStatus, EvidenceType } from "@/lib/types";

// ---------- formatters ----------
export const money = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });
export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso.length === 10 ? `${iso}T00:00` : iso).toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }) : "—";
export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-AU", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
export const pct = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n * 100)}%`);
export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

// ---------- layout ----------
export function Page({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return <div className={cx("mx-auto w-full px-4 py-6 sm:px-8 sm:py-8", wide ? "max-w-7xl" : "max-w-6xl")}>{children}</div>;
}

export function PageHeader({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:mb-8 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-2 sm:text-4xl">{title}</h1>
        {sub && <p className="mt-1.5 text-muted sm:text-lg">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

/** Dark call-out band used across the deck ("AI suggests. You approve."). */
export function Banner({ title, body, action }: { title: ReactNode; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 rounded-2xl bg-ink px-6 py-5 text-white sm:flex-row sm:items-center sm:justify-between sm:px-8">
      <div>
        <p className="font-semibold sm:text-lg">{title}</p>
        {body && <p className="mt-1 text-sm text-sage sm:text-base">{body}</p>}
      </div>
      {action}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-24 text-muted" role="status">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-brand" />
      {label}
    </div>
  );
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-3 text-sage">{icon ?? <Icon.doc className="h-10 w-10" />}</div>
      <p className="font-semibold">{title}</p>
      {body && <p className="mt-1 max-w-md text-sm text-muted">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", body, action }: { title?: string; body?: string; action?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-red/30 bg-red-bg px-6 py-5 text-red" role="alert">
      <p className="font-semibold">{title}</p>
      {body && <p className="mt-1 text-sm">{body}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function Notice({ tone = "amber", title, children }: { tone?: "amber" | "mint" | "red"; title: ReactNode; children?: ReactNode }) {
  const t = { amber: "bg-amber-bg text-amber", mint: "bg-mint text-brand-dark", red: "bg-red-bg text-red" }[tone];
  return (
    <div className={cx("rounded-xl px-5 py-4", t)}>
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-1 text-sm">{children}</div>}
    </div>
  );
}

export function Progress({ value, dark }: { value: number; dark?: boolean }) {
  return (
    <div className={cx("h-2.5 w-full overflow-hidden rounded-full", dark ? "bg-ink-3/60" : "bg-surface-2")}>
      <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Dialog({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl p-0 text-ink-2 backdrop:bg-ink/50"
    >
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        <button onClick={onClose} className="rounded-full p-1 text-muted hover:bg-surface" aria-label="Close">
          <Icon.x className="h-5 w-5" />
        </button>
      </div>
      <div className="max-h-[75vh] overflow-y-auto px-6 py-5">{open && children}</div>
    </dialog>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

/** A determinate progress bar. `value` runs from 0 to 1. */
export function ProgressBar({ value, label, className }: { value: number; label: string; className?: string }) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className={cx("h-1.5 overflow-hidden rounded-full bg-surface-2", className)}>
      <div className="h-full rounded-full bg-brand transition-[width] duration-200" style={{ width: `${percent}%` }} />
    </div>
  );
}

// ---------- badges ----------
// AI output and human decisions are styled differently everywhere on purpose.
export function AiBadge({ assessment, confidence }: { assessment: Assessment; confidence: number }) {
  const t = { strong: "bg-mint text-brand-dark", partial: "bg-amber-bg text-amber", weak: "bg-red-bg text-red" }[assessment];
  return (
    <span className={cx("pill", t)} title="AI suggestion — not verified">
      <Icon.spark className="h-3 w-3" /> AI · {assessment[0].toUpperCase() + assessment.slice(1)} — {pct(confidence)}
    </span>
  );
}

export function HumanStatus({ status, by }: { status: MatchStatus; by?: string | null }) {
  if (status === "confirmed")
    return <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-dark"><Icon.checkCircle className="h-5 w-5 text-brand" />Confirmed{by ? ` by ${by}` : ""}</span>;
  if (status === "rejected")
    return <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-muted"><Icon.xCircle className="h-5 w-5" />Rejected{by ? ` by ${by}` : ""}</span>;
  return <span className="text-sm font-semibold text-amber">Awaiting your review</span>;
}

const STATE = {
  strong: ["Strong support", "bg-brand", "text-brand-dark"],
  partial: ["Partial support", "bg-amber", "text-amber"],
  weak: ["Weak — needs review", "bg-red", "text-red"],
  missing: ["Missing evidence", "bg-muted", "text-muted"],
} as const;
export const stateColor = (s: Completeness) => STATE[s][1];
export function StateBadge({ state }: { state: Completeness }) {
  return (
    <span className={cx("inline-flex items-center gap-2 text-sm font-semibold", STATE[state][2])}>
      <span className={cx("h-2.5 w-2.5 rounded-full", STATE[state][1])} />
      {STATE[state][0]}
    </span>
  );
}

export function ProcessingBadge({ status }: { status: ProcessingStatus }) {
  const t = {
    uploaded: ["Uploaded", "bg-surface-2 text-muted"],
    processing: ["Processing…", "bg-amber-bg text-amber"],
    ready: ["Ready", "bg-mint text-brand-dark"],
    failed: ["Failed", "bg-red-bg text-red"],
  }[status];
  return <span className={cx("pill", t[1])}>{status === "processing" && <span className="h-2 w-2 animate-pulse rounded-full bg-amber" />}{t[0]}</span>;
}

export const confColor = (c: number | null) => (c == null ? "text-muted" : c >= 0.85 ? "text-brand-dark" : c >= 0.7 ? "text-amber" : "text-red");

export function EvidenceIcon({ type, className = "h-7 w-7" }: { type: EvidenceType; className?: string }) {
  const I = { photo: Icon.camera, message: Icon.mail, docket: Icon.doc, document: Icon.doc, other: Icon.doc }[type];
  return <I className={className} />;
}

// ---------- icons (inline, stroke-based) ----------
type P = { className?: string };
const svg = (d: ReactNode) =>
  function I({ className = "h-5 w-5" }: P) {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
        {d}
      </svg>
    );
  };
export const Icon = {
  camera: svg(<><path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" /><circle cx="12" cy="13" r="3.5" /></>),
  mail: svg(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></>),
  doc: svg(<><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>),
  check: svg(<path d="m5 12.5 4.5 4.5L19 7.5" />),
  checkCircle: ({ className = "h-5 w-5" }: P) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden><circle cx="12" cy="12" r="11" fill="currentColor" /><path d="m7 12.5 3.2 3.2L17 9" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" /></svg>
  ),
  xCircle: svg(<><circle cx="12" cy="12" r="9" /><path d="m9 9 6 6m0-6-6 6" /></>),
  x: svg(<path d="M6 6l12 12M18 6 6 18" />),
  bell: svg(<><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20a2 2 0 0 0 4 0" /></>),
  plus: svg(<path d="M12 5v14M5 12h14" />),
  upload: svg(<><path d="M12 16V4m0 0-4 4m4-4 4 4" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" /></>),
  search: svg(<><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4-4" /></>),
  spark: svg(<path d="M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6" />),
  arrow: svg(<path d="M5 12h14m-5-5 5 5-5 5" />),
  back: svg(<path d="M19 12H5m5-5-5 5 5 5" />),
  user: svg(<><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>),
  grid: svg(<><rect x="4" y="4" width="7" height="7" rx="1" /><rect x="13" y="4" width="7" height="7" rx="1" /><rect x="4" y="13" width="7" height="7" rx="1" /><rect x="13" y="13" width="7" height="7" rx="1" /></>),
  list: svg(<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />),
  download: svg(<><path d="M12 4v12m0 0-4-4m4 4 4-4" /><path d="M4 18v1a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-1" /></>),
  flag: svg(<path d="M5 21V4m0 0h11l-2 4 2 4H5" />),
  clock: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
};

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-2 text-lg font-bold text-white", className)}>
      <Icon.checkCircle className="h-7 w-7 text-brand" />
      SubPay
    </span>
  );
}
