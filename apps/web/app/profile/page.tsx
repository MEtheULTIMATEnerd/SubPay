"use client";
import { useEffect, useState } from "react";
import { useData } from "@/lib/store";
import { read, setAiAvailable } from "@/lib/api";
import { resetDemoData, updateProfileName } from "@/lib/auth";
import { createInvitation, listInvitations, refreshMembers, revokeInvitation } from "@/lib/members";
import type { Invitation } from "@/lib/types";
import { Dialog, ErrorState, Field, Notice, Page, PageHeader, fmtDate } from "@/components/ui";

export default function ProfilePage() {
  const db = useData();
  const user = read.me(db)!;
  const org = read.org(db);
  const members = db.profiles.filter((p) => p.organisation_id === org.id);
  const [name, setName] = useState(user.full_name);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [resetting, setResetting] = useState(false);

  // Someone may have joined since sign-in.
  useEffect(() => void refreshMembers().catch(() => undefined), []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaving(true);
    try {
      await updateProfileName(name);
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Page>
      <PageHeader title="Profile & settings" sub={org.name} />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card p-6">
          <p className="mb-4 font-semibold">Your profile</p>
          <form className="space-y-4" onSubmit={save}>
            {error && <ErrorState title={error} />}
            <Field label="Full name"><input className="input" required value={name} onChange={(e) => { setName(e.target.value); setSaved(false); }} /></Field>
            <Field label="Email"><input className="input bg-surface" value={user.email} disabled /></Field>
            <div className="flex items-center justify-end gap-3">
              {saved && <span className="text-sm text-brand-dark">Saved</span>}
              <button className="btn-dark" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
            </div>
          </form>
        </section>

        <section className="card p-6">
          <p className="mb-4 font-semibold">Organisation members</p>
          <ul className="divide-y divide-line">
            {members.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 py-3">
                <span className="min-w-0"><span className="block font-medium">{m.full_name}{m.id === user.id ? " (you)" : ""}</span><span className="block truncate text-sm text-muted">{m.email}</span></span>
                <span className="pill bg-surface-2 capitalize text-muted">{m.role}</span>
              </li>
            ))}
          </ul>
          {user.role === "owner" ? <Invitations /> : <p className="mt-4 text-sm text-muted">Only an owner can invite people to the organisation.</p>}
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
          <button className="btn-dark" onClick={() => { resetDemoData(); setResetting(false); }}>Reset</button>
        </div>
      </Dialog>
    </Page>
  );
}

/** Owners only: invite a person by email, pass on the one-time link, and revoke invitations that are still open. */
function Invitations() {
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<{ email: string; link: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const [version, setVersion] = useState(0); // bumped to load the list again
  const reload = () => setVersion((v) => v + 1);

  useEffect(() => {
    let current = true;
    listInvitations()
      .then((items) => { if (current) setInvitations(items); })
      .catch((err: Error) => { if (current) setError(err.message); });
    return () => { current = false; };
  }, [version]);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setCopied(false);
    setBusy(true);
    try {
      const { link } = await createInvitation(email);
      setCreated({ email: email.trim().toLowerCase(), link });
      setEmail("");
      reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(invitation: Invitation) {
    setError("");
    try {
      await revokeInvitation(invitation.id);
      if (created?.email === invitation.email) setCreated(null);
    } catch (err) {
      setError((err as Error).message);
    }
    reload();
  }

  async function copy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.link);
      setCopied(true);
    } catch {
      setCopied(false); // the link is in the box to copy by hand
    }
  }

  const open = invitations.filter((i) => i.status !== "accepted");

  return (
    <div className="mt-6 border-t border-line pt-5">
      <p className="font-semibold">Invite a team member</p>
      <p className="mt-1 text-sm text-muted">They join your organisation as a member and can work on its projects. SubPay does not email the link: copy it and send it to them yourself.</p>
      <form onSubmit={invite} className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1"><Field label="Their email address"><input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" /></Field></div>
        <button className="btn-dark" disabled={busy}>{busy ? "Creating…" : "Create invite link"}</button>
      </form>
      {error && <div className="mt-3"><ErrorState title={error} /></div>}

      {created && (
        <div className="mt-4">
          <Notice tone="mint" title={`Invite link for ${created.email}`}>
            <p>Copy it now. For safety it is shown only once, works once, and expires in seven days.</p>
            <div className="mt-3 flex flex-col gap-2 sm:flex-row">
              <input className="input flex-1 bg-white text-ink-2" readOnly value={created.link} aria-label="Invite link" onFocus={(e) => e.target.select()} />
              <button type="button" className="btn-dark" onClick={copy}>{copied ? "Copied" : "Copy link"}</button>
            </div>
          </Notice>
        </div>
      )}

      {open.length > 0 && (
        <>
          <p className="eyebrow mb-1 mt-5">Invitations</p>
          <ul className="divide-y divide-line">
            {open.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-3">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{i.email}</span>
                  <span className="text-sm text-muted">{i.status === "expired" ? `Expired ${fmtDate(i.expires_at)}` : `Waiting for them to join · expires ${fmtDate(i.expires_at)}`}</span>
                </span>
                <button className="btn-outline btn-sm" onClick={() => void revoke(i)} aria-label={`Revoke invitation for ${i.email}`}>Revoke</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
