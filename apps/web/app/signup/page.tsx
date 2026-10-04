"use client";
import Link from "next/link";
import { useState } from "react";
import { signUp } from "@/lib/api";
import { AuthLayout } from "@/components/auth";
import { ErrorState, Field } from "@/components/ui";

export default function SignupPage() {
  const [f, setF] = useState({ full_name: "", email: "", organisation: "", password: "" });
  const [error, setError] = useState("");
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      signUp(f); // the shell redirects once a session exists
    } catch (err) {
      setError((err as Error).message);
    }
  }

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
        <button className="btn-dark w-full py-3">Create account</button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account? <Link href="/login" className="link">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
