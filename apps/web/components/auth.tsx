"use client";
import type { ReactNode } from "react";
import { Icon, Logo } from "./ui";

const STEPS = [
  ["Read the contract", "Turns your subcontract into a claim schedule and a deadline register."],
  ["Capture the evidence", "Photos, dockets and messages saved with time, place and author."],
  ["Match to the contract", "SubPay suggests which evidence proves which line item."],
  ["Check before you send", "Flags weak lines, unbilled variations and closing notice deadlines."],
  ["Build the claim pack", "An audit-ready claim with the proof attached."],
];

export function AuthLayout({ title, sub, children }: { title: string; sub: string; children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-ink p-12 text-white lg:flex">
        <Logo className="text-2xl" />
        <div>
          <h2 className="text-4xl font-bold leading-tight">Verified progress claims,<br />from site photo to payment.</h2>
          <ol className="mt-10 space-y-5">
            {STEPS.map(([t, d], i) => (
              <li key={t} className="flex gap-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-3 text-sm font-semibold">{i + 1}</span>
                <div>
                  <p className="font-semibold">{t}</p>
                  <p className="text-sm text-sage">{d}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
        <div className="flex items-center gap-3 rounded-2xl border border-brand/50 bg-ink-3/40 px-5 py-4">
          <Icon.checkCircle className="h-8 w-8 shrink-0 text-brand" />
          <div>
            <p className="font-semibold">You approve every link</p>
            <p className="text-sm text-sage">Nothing is claimed until you confirm it. SubPay never submits on your behalf.</p>
          </div>
        </div>
      </aside>
      <section className="flex flex-col">
        <div className="bg-ink px-4 py-4 lg:hidden"><Logo /></div>
        <div className="flex flex-1 items-center justify-center px-4 py-10">
          <div className="w-full max-w-md">
            <h1 className="text-3xl font-bold">{title}</h1>
            <p className="mt-1.5 text-muted">{sub}</p>
            <div className="mt-8">{children}</div>
          </div>
        </div>
      </section>
    </div>
  );
}
