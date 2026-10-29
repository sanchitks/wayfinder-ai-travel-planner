"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthShell, PasswordField, TextField } from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/Icon";
import GoogleButton from "@/components/GoogleButton";
import { ApiError, GOOGLE_ERRORS, login, safeNext } from "@/lib/auth";

const nextPath = () => safeNext(new URLSearchParams(window.location.search).get("next"));

export default function LoginPage() {
  const { user, loading, setUser } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [qs, setQs] = useState(""); // keep ?next= when switching between log-in and sign-up
  useEffect(() => {
    setQs(window.location.search);
    const code = new URLSearchParams(window.location.search).get("error"); // sent back by the Google callback
    if (code) setError(GOOGLE_ERRORS[code] ?? "Sign-in didn't work. Please try again.");
  }, []);

  useEffect(() => {
    if (!loading && user && !busy) router.replace(nextPath()); // already signed in when the page opened
  }, [loading, user, busy, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return setError("Enter your email and password.");
    setBusy(true);
    setError("");
    try {
      setUser(await login(email, password));
      router.push(nextPath());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't log in. Please try again.");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title={<>Welcome <b>back</b></>}
      subtitle="Log in to see your saved trips and plan with your preferences."
      footer={<>New to Wayfinder? <Link href={`/signup${qs}`}>Create an account</Link></>}
    >
      <GoogleButton label="Continue with Google" />
      <div className="or-divider"><span>or log in with email</span></div>
      <form className="auth-form" onSubmit={submit} noValidate>
        <TextField label="Email" type="email" autoComplete="email" inputMode="email" value={email}
          onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required autoFocus />
        <PasswordField label="Password" autoComplete="current-password" value={password}
          onChange={(e) => setPassword(e.target.value)} required />
        {error && <div className="form-error" role="alert"><Icon name="alert" size={16} /> {error}</div>}
        <button type="submit" className="btn btn-primary btn-lg auth-submit" disabled={busy}>
          {busy ? "Logging in…" : <>Log in <Icon name="arrow" size={15} /></>}
        </button>
      </form>
    </AuthShell>
  );
}
