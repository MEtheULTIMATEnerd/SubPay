"use client";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import { signUp } from "@/lib/auth";
import { previewInvitation } from "@/lib/members";
import type { InvitationPreview } from "@/lib/types";
import { AuthLayout } from "@/components/auth";
import { ErrorState, Field, Notice } from "@/components/ui";

/** What checking an invite link found: its preview, or null when it cannot be used. */
type Checked = { code: string; preview: InvitationPreview | null; error: string };

// An invite link looks like /signup?invite=<code>. The address does not change while this page is open.
const subscribeToNothing = () => () => {};
const inviteCodeInAddress = () => new URLSearchParams(window.location.search).get("invite");

export default function SignupPage() {
  const [f, setF] = useState({ full_name: "", email: "", organisation: "", password: "" });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmEmail, setConfirmEmail] = useState(false);
  const code = useSyncExternalStore(subscribeToNothing, inviteCodeInAddress, () => null);
  const [checked, setChecked] = useState<Checked | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  // Check the invite link before showing the form.
  useEffect(() => {
    if (!code) return;
    let current = true;
    previewInvitation(code)
      .then((preview) => {
        if (!current) return;
        setChecked({ code, preview, error: "" });
        if (preview) setF((form) => ({ ...form, email: preview.email }));
      })
      .catch((err: Error) => {
        if (current) setChecked({ code, preview: null, error: err.message });
      });
    return () => { current = false; };
  }, [code]);

  const checking = !!code && checked?.code !== code;
  const joining = code && checked?.code === code ? checked.preview : null;
  const unusable = !!code && !checking && !joining;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setPending(true);
    try {
      const { needsEmailConfirmation } = await signUp(joining && code ? { ...f, invite_code: code } : f); // the shell redirects once a session exists
      if (needsEmailConfirmation) {
        setConfirmEmail(true);
        setPending(false);
      }
    } catch (err) {
      setError((err as Error).message);
      setPending(false);
    }
  }

  if (confirmEmail)
    return (
      <AuthLayout title="Check your email" sub="One more step to finish setting up your account.">
        <Notice tone="mint" title={`We sent a confirmation link to ${f.email.trim()}`}>
          Open the link to confirm your address, then sign in.
        </Notice>
        <p className="mt-6 text-center text-sm text-muted">
          <Link href="/login" className="link">Back to sign in</Link>
        </p>
      </AuthLayout>
    );

  if (checking)
    return (
      <AuthLayout title="Checking your invitation" sub="This only takes a moment.">
        <p className="text-sm text-muted" role="status">Checking the invite link…</p>
      </AuthLayout>
    );

  if (unusable)
    return (
      <AuthLayout title="This invitation can't be used" sub="Invite links work once and expire after seven days.">
        {checked?.error
          ? <ErrorState title={checked.error} body="The link could not be checked. Try again in a moment." />
          : <ErrorState title="This invite link is not valid, has already been used, or has expired." body="Ask the organisation's owner to send you a new one." />}
        <p className="mt-6 text-center text-sm text-muted">
          <Link href="/login" className="link">Sign in</Link> · <a href="/signup" className="link">Create a new organisation instead</a>
        </p>
      </AuthLayout>
    );

  return (
    <AuthLayout
      title={joining ? `Join ${joining.organisation_name}` : "Create your account"}
      sub={joining ? "You've been invited to join this organisation on SubPay as a team member." : "Set up your subcontracting business on SubPay."}
    >
      <form onSubmit={submit} className="space-y-4">
        {error && <ErrorState title={error} />}
        <Field label="Full name"><input className="input" required autoComplete="name" value={f.full_name} onChange={set("full_name")} /></Field>
        {!joining && (
          <Field label="Business name" hint="You'll be the owner of this organisation.">
            <input className="input" required value={f.organisation} onChange={set("organisation")} placeholder="e.g. Kearney Formwork Pty Ltd" />
          </Field>
        )}
        <Field label="Email" hint={joining ? "The invitation is for this address." : undefined}>
          <input className={joining ? "input bg-surface" : "input"} type="email" required autoComplete="email" value={f.email} onChange={set("email")} readOnly={!!joining} />
        </Field>
        <Field label="Password" hint="At least 8 characters.">
          <input className="input" type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={set("password")} />
        </Field>
        <button className="btn-dark w-full py-3" disabled={pending}>
          {pending ? (joining ? "Joining…" : "Creating account…") : joining ? `Join ${joining.organisation_name}` : "Create account"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account? <Link href="/login" className="link">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
