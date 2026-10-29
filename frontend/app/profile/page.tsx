"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { PasswordField, TextField, passwordStrength } from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/Icon";
import Avatar from "@/components/Avatar";
import ThemeSwitch from "@/components/ThemeSwitch";
import UserMenu from "@/components/UserMenu";
import {
  ApiError, changePassword, deleteAccount, deleteTrip, downloadMyData, listTrips, updateProfile,
  type ProfileInput, type TripSummary, type User,
} from "@/lib/auth";
import { DIETS, INTERESTS, PERSONAS, money, nightsBetween, shortDate } from "@/lib/format";
import { destinationPhoto } from "@/lib/photos";

type Tab = "profile" | "trips" | "security";

const toInput = (u: User): ProfileInput => ({
  name: u.name, phone: u.phone, home_city: u.home_city, persona: u.persona, budget: u.budget,
  diets: u.diets, interests: u.interests, bio: u.bio,
});

function toggleDiet(current: string[], d: string): string[] {
  if (current.includes(d)) return current.filter((x) => x !== d);
  return d === "Non veg" ? [d] : [...current.filter((x) => x !== "Non veg"), d];
}

function ProfileForm({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [form, setForm] = useState<ProfileInput>(toInput(user));
  const [budgetText, setBudgetText] = useState(user.budget ? String(user.budget) : "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [message, setMessage] = useState("");
  const set = <K extends keyof ProfileInput>(k: K, v: ProfileInput[K]) => {
    setForm((f) => ({ ...f, [k]: v }));
    setStatus("idle");
  };
  const dirty = JSON.stringify(form) !== JSON.stringify(toInput(user));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    const digits = budgetText.replace(/\D/g, "");
    const budget = digits ? Number(digits) : null;
    if (budget !== null && (budget < 5000 || budget > 1000000)) {
      setErrors({ budget: "Between ₹5,000 and ₹10,00,000, or leave it empty." });
      return;
    }
    setStatus("saving");
    try {
      const u = await updateProfile({ ...form, budget });
      onSaved(u);
      setForm(toInput(u));
      setStatus("saved");
    } catch (err) {
      setStatus("error");
      if (err instanceof ApiError) {
        setErrors(err.fields);
        setMessage(err.message);
      } else setMessage("Couldn't save. Please try again.");
    }
  }

  return (
    <form className="card profile-card" onSubmit={save} noValidate>
      <div className="profile-section">
        <h3>Personal details</h3>
        <div className="grid-2">
          <TextField label="Name" value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={80} error={errors.name} autoComplete="name" />
          <TextField label="Email" value={user.email} readOnly disabled hint="Your login email can't be changed here." />
          <TextField label="Phone (optional)" value={form.phone} onChange={(e) => set("phone", e.target.value)} type="tel"
            inputMode="tel" placeholder="+91 98765 43210" error={errors.phone} autoComplete="tel" maxLength={20} />
          <TextField label="Home city" value={form.home_city} onChange={(e) => set("home_city", e.target.value)}
            placeholder="e.g. Delhi, Mumbai, Pune" hint="Used as the 'From' city for new trips." error={errors.home_city} maxLength={80} />
        </div>
        <div className="field" style={{ marginTop: 14 }}>
          <label htmlFor="bio">About you (optional)</label>
          <textarea id="bio" className="input" rows={3} maxLength={500} value={form.bio} onChange={(e) => set("bio", e.target.value)}
            placeholder="e.g. Weekend explorer, love heritage walks and street food." />
          <div className="tiny muted" style={{ textAlign: "right" }}>{form.bio.length}/500</div>
        </div>
      </div>

      <div className="profile-section">
        <h3>Travel preferences</h3>
        <p className="small muted" style={{ marginTop: -6 }}>These pre-fill the trip planner. You can still change them for any trip.</p>
        <div className="label" style={{ marginBottom: 8 }}>Usual travel style</div>
        <div className="row wrap">
          {PERSONAS.map((p) => (
            <button type="button" key={p.key} className="chip" aria-pressed={form.persona === p.key} onClick={() => set("persona", p.key)}>
              {form.persona === p.key && <Icon name="check" size={13} />} {p.label}
            </button>
          ))}
        </div>
        <div className="grid-2" style={{ marginTop: 16 }}>
          <TextField label="Usual trip budget (optional)" inputMode="numeric" placeholder="e.g. 50,000"
            value={budgetText ? Number(budgetText.replace(/\D/g, "") || 0).toLocaleString("en-IN") : ""}
            onChange={(e) => { setBudgetText(e.target.value.replace(/\D/g, "").slice(0, 7)); setStatus("idle"); }}
            error={errors.budget} hint="Total for a trip, in rupees." />
        </div>
        <div className="label" style={{ margin: "16px 0 8px" }}>Food preferences</div>
        <div className="row wrap">
          {DIETS.map((d) => (
            <button type="button" key={d} className="chip" aria-pressed={form.diets.includes(d)} onClick={() => set("diets", toggleDiet(form.diets, d))}>
              {form.diets.includes(d) && <Icon name="check" size={13} />} {d}
            </button>
          ))}
        </div>
        {errors.diets && <div className="tiny field-error">{errors.diets}</div>}
        <div className="label" style={{ margin: "16px 0 8px" }}>Interests</div>
        <div className="row wrap">
          {INTERESTS.map((i) => (
            <button type="button" key={i} className="chip" aria-pressed={form.interests.includes(i)}
              onClick={() => set("interests", form.interests.includes(i) ? form.interests.filter((x) => x !== i) : [...form.interests, i])}>
              {form.interests.includes(i) && <Icon name="check" size={13} />} {i}
            </button>
          ))}
        </div>
      </div>

      <div className="profile-actions">
        <span className={`small ${status === "error" ? "field-error" : status === "saved" ? "saved-note" : "muted"}`} role="status">
          {status === "saved" ? "✓ Profile saved" : status === "error" ? message : dirty || budgetText !== (user.budget ? String(user.budget) : "") ? "You have unsaved changes" : ""}
        </span>
        <button type="submit" className="btn btn-primary" disabled={status === "saving"}>
          {status === "saving" ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function Trips({ onCount }: { onCount: (n: number) => void }) {
  const [trips, setTrips] = useState<TripSummary[] | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const t = await listTrips();
      setTrips(t);
      onCount(t.length);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load your trips.");
    }
  }, [onCount]);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(id: string) {
    try {
      await deleteTrip(id);
      setConfirming(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete that trip.");
    }
  }

  if (error) return <div className="form-error" role="alert"><Icon name="alert" size={16} /> {error}</div>;
  if (!trips) return <div className="trip-grid">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 280 }} />)}</div>;
  if (!trips.length) {
    return (
      <div className="card empty-state">
        <Icon name="bookmark" size={28} />
        <h3>No saved trips yet</h3>
        <p className="muted">Every trip you plan while logged in is saved here automatically.</p>
        <Link href="/" className="btn btn-primary">Plan a trip <Icon name="arrow" size={14} /></Link>
      </div>
    );
  }
  return (
    <div className="trip-grid">
      {trips.map((t) => {
        const img = destinationPhoto(t.destination) ?? t.image;
        const nights = nightsBetween(t.start_date, t.end_date);
        return (
          <article key={t.id} className="card trip-card">
            <Link href={`/?trip=${t.id}`} className="trip-photo" style={img ? { backgroundImage: `url("${img}")` } : undefined} aria-label={`Open ${t.title}`}>
              <span className="photo-plate">{t.destination}</span>
            </Link>
            <div className="trip-body">
              <h3>{t.title}</h3>
              <div className="small muted">{shortDate(t.start_date)} – {shortDate(t.end_date)} · {nights} night{nights === 1 ? "" : "s"}</div>
              <div className="row wrap" style={{ gap: 6 }}>
                <span className="tag">{PERSONAS.find((p) => p.key === t.persona)?.label ?? t.persona}</span>
                <span className="tag tag-accent">≈ {money(t.total)}</span>
                {t.version > 1 && <span className="tag">Version {t.version}</span>}
              </div>
              <div className="tiny muted">Saved {new Date(t.updated_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</div>
              {confirming === t.id ? (
                <div className="trip-actions confirm">
                  <span className="small">Delete this trip?</span>
                  <button className="btn btn-sm danger-btn" onClick={() => remove(t.id)}>Delete</button>
                  <button className="btn btn-sm" onClick={() => setConfirming(null)}>Keep</button>
                </div>
              ) : (
                <div className="trip-actions">
                  <Link href={`/?trip=${t.id}`} className="btn btn-sm btn-primary">Open trip</Link>
                  <button className="btn btn-sm btn-ghost" onClick={() => setConfirming(t.id)} aria-label={`Delete ${t.title}`}>
                    <Icon name="trash" size={14} /> Delete
                  </button>
                </div>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function YourData() {
  const [state, setState] = useState<{ busy?: boolean; ok?: string; error?: string }>({});
  async function download() {
    setState({ busy: true });
    try {
      await downloadMyData();
      setState({ ok: "Downloaded." });
    } catch (err) {
      setState({ error: err instanceof ApiError ? err.message : "Couldn't prepare your data." });
    }
  }
  return (
    <div className="card profile-card">
      <div className="profile-section">
        <h3><Icon name="download" size={18} /> Your data</h3>
        <p className="small muted" style={{ marginTop: -4 }}>
          Download a copy of everything Wayfinder stores about you: your profile, saved trips with their full itineraries,
          sign-in methods and the pages you visited while signed in. Your password is never included. It&apos;s only kept as a one-way hash.
        </p>
        <Link href="/privacy" className="small">Read the Privacy Policy</Link>
      </div>
      <div className="profile-actions">
        <span className={`small ${state.error ? "field-error" : "saved-note"}`} role="status">{state.error ?? state.ok ?? ""}</span>
        <button type="button" className="btn btn-primary" onClick={download} disabled={state.busy}>
          <Icon name="download" size={15} /> {state.busy ? "Preparing…" : "Download my data"}
        </button>
      </div>
    </div>
  );
}

function Security({ user, onDeleted, onPasswordSet }: { user: User; onDeleted: () => void; onPasswordSet: () => void }) {
  const hasPassword = user.has_password;
  const google = user.linked_providers.includes("google");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [pwState, setPwState] = useState<{ ok?: string; error?: string; busy?: boolean }>({});
  const [delPw, setDelPw] = useState("");
  const [delSure, setDelSure] = useState(false);
  const [delState, setDelState] = useState<{ error?: string; busy?: boolean }>({});
  const strength = passwordStrength(next);

  async function change(e: React.FormEvent) {
    e.preventDefault();
    if (hasPassword && !current) return setPwState({ error: "Enter your current password." });
    if (!strength.ok) return setPwState({ error: strength.label || "Choose a new password." });
    setPwState({ busy: true });
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setPwState({ ok: hasPassword ? "Password changed. Other devices have been logged out." : "Password set. You can now also log in with your email." });
      if (!hasPassword) onPasswordSet();
    } catch (err) {
      setPwState({ error: err instanceof ApiError ? err.message : "Couldn't change your password." });
    }
  }

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    if (!delSure) return setDelState({ error: "Tick the box to confirm." });
    setDelState({ busy: true });
    try {
      await (hasPassword ? deleteAccount(delPw) : deleteAccount("", delPw.trim()));
      onDeleted();
    } catch (err) {
      setDelState({ error: err instanceof ApiError ? err.message : "Couldn't delete your account." });
    }
  }

  return (
    <div className="security-grid">
      <div className="card profile-card linked-card">
        <div className="profile-section">
          <h3><Icon name="user" size={18} /> Sign-in methods</h3>
          <div className="signin-method">
            <Icon name="mail" size={18} />
            <div className="grow"><b>Email and password</b><div className="tiny muted">{user.email}</div></div>
            <span className={`tag ${hasPassword ? "tag-leaf" : ""}`}>{hasPassword ? "Set" : "Not set"}</span>
          </div>
          <div className="signin-method">
            <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" /><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" /><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" /><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" /></svg>
            <div className="grow"><b>Google</b><div className="tiny muted">{google ? "Linked - use “Continue with Google” to log in" : "Log in with “Continue with Google” using this email to link it"}</div></div>
            <span className={`tag ${google ? "tag-leaf" : ""}`}>{google ? "Linked" : "Not linked"}</span>
          </div>
        </div>
      </div>

      <form className="card profile-card" onSubmit={change} noValidate>
        <div className="profile-section">
          <h3><Icon name="lock" size={18} /> {hasPassword ? "Change password" : "Set a password"}</h3>
          {hasPassword ? (
            <>
              <PasswordField label="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
              <div style={{ height: 12 }} />
            </>
          ) : (
            <p className="small muted" style={{ marginTop: -4 }}>You signed up with Google. Add a password if you&apos;d also like to log in with your email.</p>
          )}
          <PasswordField label="New password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} maxLength={128}
            hint="At least 8 characters, with letters and numbers or symbols." />
          {next && (
            <div className="strength" data-score={strength.score}><span className="strength-bar"><i /><i /><i /></span><span className="tiny">{strength.label}</span></div>
          )}
        </div>
        <div className="profile-actions">
          <span className={`small ${pwState.error ? "field-error" : "saved-note"}`} role="status">{pwState.error ?? pwState.ok ?? ""}</span>
          <button className="btn btn-primary" disabled={pwState.busy}>{pwState.busy ? "Saving…" : hasPassword ? "Change password" : "Set password"}</button>
        </div>
      </form>

      <YourData />

      <form className="card profile-card danger-zone" onSubmit={remove} noValidate>
        <div className="profile-section">
          <h3><Icon name="trash" size={18} /> Delete account</h3>
          <p className="small muted" style={{ marginTop: -4 }}>Permanently deletes your profile, saved trips and linked Google sign-in. This can&apos;t be undone.</p>
          {hasPassword ? (
            <PasswordField label="Confirm with your password" autoComplete="current-password" value={delPw} onChange={(e) => setDelPw(e.target.value)} />
          ) : (
            <TextField label="Type DELETE to confirm" value={delPw} onChange={(e) => setDelPw(e.target.value)} autoComplete="off" />
          )}
          <label className="toggle" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={delSure} onChange={(e) => setDelSure(e.target.checked)} />
            I understand my trips will be deleted too
          </label>
        </div>
        <div className="profile-actions">
          <span className="small field-error" role="status">{delState.error ?? ""}</span>
          <button className="btn danger-btn" disabled={delState.busy || !delPw}>{delState.busy ? "Deleting…" : "Delete my account"}</button>
        </div>
      </form>
    </div>
  );
}

export default function ProfilePage() {
  const { user, loading, setUser } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("profile");
  const [welcome, setWelcome] = useState(false);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const t = q.get("tab");
    if (t === "trips" || t === "security") setTab(t);
    setWelcome(q.get("welcome") === "1");
  }, []);

  const leaving = useRef(false); // account just deleted: go home, not to the login page

  useEffect(() => {
    if (!loading && !user && !leaving.current) router.replace("/login?next=/profile");
  }, [loading, user, router]);

  const onCount = useCallback((n: number) => setUser((u) => (u ? { ...u, trip_count: n } : u)), [setUser]);

  const go = (t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", t === "profile" ? "/profile" : `/profile?tab=${t}`);
  };

  if (loading || !user) {
    return <div className="profile-page"><div className="profile-inner"><div className="skeleton" style={{ height: 180 }} /></div></div>;
  }

  return (
    <div className="profile-page">
      <header className="profile-topbar">
        <Link href="/" className="brand"><span className="brand-mark"><Icon name="compass" size={19} /></span> Wayfinder</Link>
        <div className="row" style={{ marginLeft: "auto", gap: 10 }}>
          <Link href="/" className="btn btn-sm btn-primary hide-xs">Plan a trip</Link>
          <ThemeSwitch />
          <UserMenu compact />
        </div>
      </header>

      <section className="profile-hero">
        <div className="profile-inner profile-hero-inner">
          <Avatar user={user} large />
          <div className="grow">
            <div className="eyebrow" style={{ color: "#fff", borderColor: "#fff" }}>My profile</div>
            <h1 className="profile-name">{user.name}</h1>
            <div className="profile-meta">
              <span><Icon name="mail" size={14} /> {user.email}</span>
              {user.home_city && <span><Icon name="pin" size={14} /> {user.home_city}</span>}
              <span><Icon name="calendar" size={14} /> Member since {new Date(user.created_at).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</span>
              <span><Icon name="bookmark" size={14} /> {user.trip_count} saved trip{user.trip_count === 1 ? "" : "s"}</span>
            </div>
          </div>
        </div>
      </section>

      <div className="profile-inner">
        {welcome && (
          <div className="welcome-note" role="status">
            <Icon name="sparkles" size={18} />
            <div><b>Welcome to Wayfinder, {user.name.split(" ")[0]}!</b> Add your home city and travel preferences below. They&apos;ll pre-fill every trip you plan.</div>
            <button className="btn btn-sm btn-ghost" onClick={() => setWelcome(false)} aria-label="Dismiss"><Icon name="x" size={14} /></button>
          </div>
        )}
        <nav className="tabs profile-tabs" role="tablist" aria-label="Profile sections">
          <button role="tab" className="tab" aria-selected={tab === "profile"} onClick={() => go("profile")}><Icon name="user" size={15} /> Profile</button>
          <button role="tab" className="tab" aria-selected={tab === "trips"} onClick={() => go("trips")}>
            <Icon name="bookmark" size={15} /> Saved trips <span className="count">{user.trip_count}</span>
          </button>
          <button role="tab" className="tab" aria-selected={tab === "security"} onClick={() => go("security")}><Icon name="lock" size={15} /> Security</button>
        </nav>
        {tab === "profile" && <ProfileForm key={user.id} user={user} onSaved={setUser} />}
        {tab === "trips" && <Trips onCount={onCount} />}
        {tab === "security" && <Security user={user} onPasswordSet={() => setUser((u) => (u ? { ...u, has_password: true } : u))}
          onDeleted={() => { leaving.current = true; setUser(null); router.replace("/"); }} />}
      </div>
    </div>
  );
}
