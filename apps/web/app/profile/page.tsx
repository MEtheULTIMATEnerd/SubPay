"use client";
import { useState } from "react";
import { useData } from "@/lib/store";
import { read, resetDemo, setAiAvailable, updateProfile } from "@/lib/api";
import { Dialog, Field, Page, PageHeader } from "@/components/ui";

export default function ProfilePage() {
  const db = useData();
  const user = read.me(db)!;
  const org = read.org(db);
  const members = db.profiles.filter((p) => p.organisation_id === org.id);
  const [name, setName] = useState(user.full_name);
  const [saved, setSaved] = useState(false);
  const [resetting, setResetting] = useState(false);

  return (
    <Page>
      <PageHeader title="Profile & settings" sub={org.name} />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <p className="mb-4 font-semibold">Your profile</p>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); updateProfile(name); setSaved(true); }}>
            <Field label="Full name"><input className="input" required value={name} onChange={(e) => { setName(e.target.value); setSaved(false); }} /></Field>
            <Field label="Email"><input className="input bg-surface" value={user.email} disabled /></Field>
            <div className="flex items-center justify-end gap-3">
              {saved && <span className="text-sm text-brand-dark">Saved</span>}
              <button className="btn-dark">Save</button>
            </div>
          </form>
        </section>

        <section className="card p-6">
          <p className="mb-4 font-semibold">Organisation members</p>
          <ul className="divide-y divide-line">
            {members.map((m) => (
              <li key={m.id} className="flex items-center justify-between py-3">
                <span><span className="block font-medium">{m.full_name}</span><span className="text-sm text-muted">{m.email}</span></span>
                <span className="pill bg-surface-2 capitalize text-muted">{m.role}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card p-6 lg:col-span-2">
          <p className="font-semibold">Prototype controls</p>
          <p className="mt-1 text-sm text-muted">Data lives in this browser only. These controls exist for demos and testing.</p>
          <div className="mt-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <label className="flex items-center gap-3">
              <input type="checkbox" className="h-5 w-5 accent-brand" checked={!db.settings.ai_available} onChange={(e) => setAiAvailable(!e.target.checked)} />
              <span><span className="block font-medium">Simulate AI outage</span><span className="text-sm text-muted">Extraction and matching fail; manual review still works.</span></span>
            </label>
            <button className="btn-danger" onClick={() => setResetting(true)}>Reset demo data</button>
          </div>
        </section>
      </div>

      <Dialog open={resetting} onClose={() => setResetting(false)} title="Reset demo data?">
        <p className="text-sm text-muted">This restores the Hume St Tower demo and discards everything you&apos;ve added in this browser.</p>
        <div className="mt-6 flex justify-end gap-2">
          <button className="btn-outline" onClick={() => setResetting(false)}>Cancel</button>
          <button className="btn-dark" onClick={() => { resetDemo(); setResetting(false); }}>Reset</button>
        </div>
      </Dialog>
    </Page>
  );
}
