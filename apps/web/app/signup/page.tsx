"use client";
import Link from "next/link";
import { useState } from "react";
import { signUp } from "@/lib/auth";
import { AuthLayout } from "@/components/auth";
import { ErrorState, Field, Notice } from "@/components/ui";

export default function SignupPage() {
  const [f, setF] = useState({ full_name: "", email: "", organisation: "", password: "" });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmEmail, setConfirmEmail] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setPending(true);
    try {
      const { needsEmailConfirmation } = await signUp(f); // the shell redirects once a session exists
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

  return (
    <AuthLayout title="Create your account" sub="Set up your subcontracting business on SubPay.">
      <form onSubmit={submit} className="space-y-4">
        {error && <ErrorState title={error} />}
        <Field label="Full name"><input className="input" required autoComplete="name" value={f.full_name} onChange={set("full_name")} /></Field>
        <Field label="Business name" hint="You'll be the owner of this organisation.">
          <input className="input" required value={f.organisation} onChange={set("organisation")} placeholder="e.g. Kearney Formwork Pty Ltd" />
        </Field>
        <Field label="Email"><input className="input" type="email" required autoComplete="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Password" hint="At least 8 characters.">
          <input className="input" type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={set("password")} />
        </Field>
        <button className="btn-dark w-full py-3" disabled={pending}>{pending ? "Creating account…" : "Create account"}</button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account? <Link href="/login" className="link">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
