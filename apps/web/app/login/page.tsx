"use client";
import Link from "next/link";
import { useState } from "react";
import { signIn, useAuth } from "@/lib/auth";
import { LIVE } from "@/lib/env";
import { AuthLayout } from "@/components/auth";
import { ErrorState, Field } from "@/components/ui";

const DEMO_EMAIL = "ollie@kearneyformwork.test";

export default function LoginPage() {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(e?: React.FormEvent, creds = { email, password }) {
    e?.preventDefault();
    setError("");
    setPending(true);
    try {
      await signIn(creds.email, creds.password); // the shell redirects once a session exists
    } catch (err) {
      setError((err as Error).message);
      setPending(false);
    }
  }

  const problem = error || auth.error;

  return (
    <AuthLayout title="Sign in" sub="Welcome back. Pick up where your crew left off.">
      <form onSubmit={submit} className="space-y-4">
        {problem && <ErrorState title={problem} />}
        <Field label="Email">
          <input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <button className="btn-dark w-full py-3" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
      </form>
      {!LIVE && (
        <div className="mt-6 rounded-xl border border-line bg-white p-4 text-sm">
          <p className="font-semibold">Demo account</p>
          <p className="mt-1 text-muted">Ollie Reid · Kearney Formwork Pty Ltd (owner). Any password works in the prototype.</p>
          <button onClick={() => submit(undefined, { email: DEMO_EMAIL, password: "demo" })} className="btn-primary mt-3 w-full" disabled={pending}>
            Continue as demo user
          </button>
        </div>
      )}
      <p className="mt-6 text-center text-sm text-muted">
        New to SubPay? <Link href="/signup" className="link">Create an account</Link>
      </p>
    </AuthLayout>
  );
}
