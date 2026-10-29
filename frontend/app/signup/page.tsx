"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthShell, PasswordField, TextField, passwordStrength } from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/Icon";
import GoogleButton from "@/components/GoogleButton";
import { ApiError, safeNext, signup } from "@/lib/auth";

export default function SignupPage() {
  const { user, loading, setUser } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [qs, setQs] = useState(""); // keep ?next= when switching between log-in and sign-up
  useEffect(() => setQs(window.location.search), []);
  const strength = passwordStrength(password);

  useEffect(() => {
    // Already signed in when the page opened (not just signed up here: submit handles that redirect).
    if (!loading && user && !busy) router.replace("/profile");
  }, [loading, user, busy, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const local: Record<string, string> = {};
    if (!name.trim()) local.name = "Tell us your name.";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email.trim())) local.email = "Enter a valid email address.";
    if (!strength.ok) local.password = strength.label || "Choose a password.";
    setErrors(local);
    setError("");
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      setUser(await signup(name, email, password));
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next ? safeNext(next) : "/profile?welcome=1");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields);
        if (!Object.keys(err.fields).length) setError(err.message);
      } else setError("Couldn't create your account. Please try again.");
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title={<>Create your <b>account</b></>}
      subtitle="Free. Save your trips and let your preferences pre-fill every plan."
      footer={<>Already have an account? <Link href={`/login${qs}`}>Log in</Link></>}
    >
      <GoogleButton label="Sign up with Google" />
      <div className="or-divider"><span>or sign up with email</span></div>
      <form className="auth-form" onSubmit={submit} noValidate>
        <TextField label="Your name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Priya Sharma" error={errors.name} maxLength={80} autoFocus />
        <TextField label="Email" type="email" autoComplete="email" inputMode="email" value={email}
          onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" error={errors.email} />
        <PasswordField label="Password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)}
          error={errors.password} hint={password ? undefined : "At least 8 characters, with letters and numbers or symbols."} maxLength={128} />
        {password && (
          <div className="strength" data-score={strength.score} aria-live="polite">
            <span className="strength-bar"><i /><i /><i /></span>
            <span className="tiny">{strength.label}</span>
          </div>
        )}
        {error && <div className="form-error" role="alert"><Icon name="alert" size={16} /> {error}</div>}
        <button type="submit" className="btn btn-primary btn-lg auth-submit" disabled={busy}>
          {busy ? "Creating account…" : <>Create account <Icon name="arrow" size={15} /></>}
        </button>
        <p className="tiny muted" style={{ margin: 0 }}>
          By creating an account you agree to our <Link href="/privacy">Privacy Policy</Link>. Your password is stored only as a
          secure hash, and we never sell your details.
        </p>
      </form>
    </AuthShell>
  );
}
