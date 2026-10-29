"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { PHOTO_CREDITS } from "@/lib/photos";
import { Icon } from "./Icon";
import ThemeSwitch from "./ThemeSwitch";

/** Shared layout for the log-in and sign-up pages: a photo panel and the form card. */
export function AuthShell({ title, subtitle, children, footer }: {
  title: React.ReactNode; subtitle: string; children: React.ReactNode; footer: React.ReactNode;
}) {
  const credit = PHOTO_CREDITS.udaipur;
  return (
    <div className="auth-page">
      <aside className="auth-photo" style={{ backgroundImage: "url(/photos/udaipur.jpg)" }}>
        <Link href="/" className="brand auth-brand">
          <span className="brand-mark"><Icon name="compass" size={19} /></span> Wayfinder
        </Link>
        <div className="auth-pitch">
          <h2>Every trip you plan, <span className="hero-mark">saved for you</span></h2>
          <ul>
            <li><Icon name="bookmark" size={18} /> Your itineraries are saved automatically - reopen them any time</li>
            <li><Icon name="sparkles" size={18} /> Your home city, style, budget and diet pre-fill every new trip</li>
            <li><Icon name="lock" size={18} /> Your data stays private to your account</li>
          </ul>
        </div>
        <a className="photo-credit" href={credit.source} target="_blank" rel="noreferrer">{credit.title} · {credit.author} · {credit.license}</a>
      </aside>
      <main className="auth-main">
        <div className="auth-top">
          <Link href="/" className="btn btn-sm btn-ghost"><Icon name="arrow" size={14} style={{ transform: "rotate(180deg)" }} /> Back to planner</Link>
          <ThemeSwitch />
        </div>
        <div className="auth-card">
          <div className="eyebrow">Wayfinder account</div>
          <h1 className="section-heading" style={{ marginBottom: 6 }}>{title}</h1>
          <p className="muted" style={{ margin: "0 0 22px" }}>{subtitle}</p>
          {children}
          <div className="auth-footer">{footer}</div>
        </div>
      </main>
    </div>
  );
}

export function TextField({ label, error, hint, ...input }: {
  label: string; error?: string; hint?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className={`input${error ? " input-error" : ""}`} aria-invalid={!!error}
        aria-describedby={error || hint ? `${id}-msg` : undefined} {...input} />
      {(error || hint) && <div id={`${id}-msg`} className={`tiny ${error ? "field-error" : "muted"}`}>{error || hint}</div>}
    </div>
  );
}

export function PasswordField({ label, error, hint, ...input }: {
  label: string; error?: string; hint?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  const [show, setShow] = useState(false);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="password-box">
        <input id={id} type={show ? "text" : "password"} className={`input${error ? " input-error" : ""}`} aria-invalid={!!error}
          aria-describedby={error || hint ? `${id}-msg` : undefined} {...input} />
        <button type="button" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"} title={show ? "Hide password" : "Show password"}>
          <Icon name={show ? "eyeOff" : "eye"} size={17} />
        </button>
      </div>
      {(error || hint) && <div id={`${id}-msg`} className={`tiny ${error ? "field-error" : "muted"}`}>{error || hint}</div>}
    </div>
  );
}

/** Rough strength meter: length plus character variety. Matches the server's minimum rules. */
export function passwordStrength(p: string): { score: 0 | 1 | 2 | 3; label: string; ok: boolean } {
  const ok = p.length >= 8 && !/^\d+$/.test(p) && !/^[a-zA-Z]+$/.test(p);
  if (!p) return { score: 0, label: "", ok: false };
  if (!ok) return { score: 1, label: p.length < 8 ? "At least 8 characters" : "Mix letters with numbers or symbols", ok };
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^a-zA-Z0-9]/].filter((r) => r.test(p)).length;
  return p.length >= 12 && variety >= 3 ? { score: 3, label: "Strong", ok } : { score: 2, label: "Good", ok };
}
