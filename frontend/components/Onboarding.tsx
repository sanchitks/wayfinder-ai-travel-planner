"use client";

import { useEffect, useMemo, useState } from "react";
import { AGENTS, DIETS, INTERESTS, PERSONAS, POPULAR_DESTINATIONS, isoDate, money, nightsBetween } from "@/lib/format";
import Link from "next/link";
import { PHOTO_CREDITS, destinationPhoto } from "@/lib/photos";
import { asset } from "@/lib/site";
import type { Health, Persona, TripRequest } from "@/lib/types";
import { Icon, type IconName } from "./Icon";
import ThemeSwitch from "./ThemeSwitch";
import UserMenu from "./UserMenu";
import type { User } from "@/lib/auth";

const PERSONA_ICON: Record<Persona, IconName> = {
  budget: "backpack",
  luxury: "crown",
  business: "briefcase",
  family: "users",
};

export const AGENT_ICON = {
  orchestrator: "sparkles",
  logistics: "plane",
  accommodation: "bed",
  experience: "compass",
} as const satisfies Record<string, IconName>;

// Budgets in India span weekend trips to luxury holidays, so the slider is logarithmic.
const BUDGET_MIN = 5000;
const BUDGET_MAX = 1000000;
const budgetToSlider = (b: number) =>
  Math.round((1000 * Math.log(Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, b)) / BUDGET_MIN)) / Math.log(BUDGET_MAX / BUDGET_MIN));
// Labels sit at their true positions on the log scale (evenly spaced labels would be wrong).
const BUDGET_TICKS: [number, string][] = [[5000, "₹5K"], [25000, "₹25K"], [100000, "₹1L"], [300000, "₹3L"], [1000000, "₹10L"]];
const THUMB_PX = 18; // keep in sync with .budget-range thumb size

function sliderToBudget(pos: number) {
  const raw = BUDGET_MIN * Math.pow(BUDGET_MAX / BUDGET_MIN, pos / 1000);
  const step = raw < 50000 ? 500 : raw < 200000 ? 1000 : 5000;
  return Math.round(raw / step) * step;
}

export function defaultRequest(): TripRequest {
  const start = new Date();
  start.setDate(start.getDate() + 30);
  const end = new Date(start);
  end.setDate(end.getDate() + 5);
  return {
    origin: "Delhi",
    destination: "",
    start_date: isoDate(start),
    end_date: isoDate(end),
    adults: 2,
    children: 0,
    budget: PERSONAS[0].budget,
    persona: "budget",
    interests: ["Food"],
    flexible_dates: true,
    work_location: null,
    notes: "",
  };
}

/** "Non veg" can't be combined with the vegetarian diets, so picking one side clears the other. */
function toggleDiet(current: string[], d: string): string[] {
  if (current.includes(d)) return current.filter((x) => x !== d);
  return d === "Non veg" ? [d] : [...current.filter((x) => x !== "Non veg"), d];
}

function Stepper({ value, min, max, onChange, label }: { value: number; min: number; max: number; onChange: (v: number) => void; label: string }) {
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" onClick={() => onChange(value - 1)} disabled={value <= min} aria-label={`Fewer ${label}`}>−</button>
      <span aria-live="polite">{value}</span>
      <button type="button" onClick={() => onChange(value + 1)} disabled={value >= max} aria-label={`More ${label}`}>+</button>
    </div>
  );
}

/** A signed-in user's saved preferences applied to a fresh trip form. */
export function applyProfile(r: TripRequest, u: User): TripRequest {
  const persona = u.persona;
  return {
    ...r,
    origin: u.home_city || r.origin,
    persona,
    budget: u.budget ?? PERSONAS.find((p) => p.key === persona)!.budget,
    interests: u.interests.length ? u.interests : r.interests,
    children: persona === "family" && r.children === 0 ? 2 : r.children,
    adults: persona === "business" ? 1 : r.adults,
    flexible_dates: persona === "budget" ? true : r.flexible_dates,
  };
}

export default function Onboarding({
  initial,
  initialDiets = [],
  budgetLocked = false,
  health,
  onSubmit,
}: {
  initial: TripRequest;
  /** Diets from the user's profile. */
  initialDiets?: string[];
  /** The budget came from the profile, so switching travel style shouldn't replace it. */
  budgetLocked?: boolean;
  health: Health | null | undefined;
  onSubmit: (req: TripRequest) => void;
}) {
  const [req, setReq] = useState<TripRequest>(initial);
  const [budgetTouched, setBudgetTouched] = useState(initial.destination !== "" || budgetLocked);
  const [error, setError] = useState<string | null>(null);
  const [diets, setDiets] = useState<string[]>(initialDiets);
  const [budgetText, setBudgetText] = useState<string | null>(null); // what's in the box while the amount is being typed
  const typed = budgetText === null ? null : Number(budgetText.replace(/\D/g, "") || 0);
  const budgetOutOfRange = typed !== null && budgetText !== "" && (typed < BUDGET_MIN || typed > BUDGET_MAX);
  const set = <K extends keyof TripRequest>(k: K, v: TripRequest[K]) => setReq((r) => ({ ...r, [k]: v }));

  const nights = nightsBetween(req.start_date, req.end_date);
  const today = isoDate(new Date());
  const perNight = useMemo(() => (nights > 0 ? req.budget / nights / (req.adults + req.children) : 0), [req, nights]);

  function pickPersona(p: Persona) {
    setReq((r) => ({
      ...r,
      persona: p,
      budget: budgetTouched ? r.budget : PERSONAS.find((x) => x.key === p)!.budget,
      flexible_dates: p === "budget" ? true : r.flexible_dates,
      children: p === "family" && r.children === 0 ? 2 : p !== "family" && r.persona === "family" ? 0 : r.children,
      adults: p === "business" && r.persona !== "business" ? 1 : r.adults,
    }));
  }

  function toggleInterest(i: string) {
    set("interests", req.interests.includes(i) ? req.interests.filter((x) => x !== i) : [...req.interests, i]);
  }

  function fail(message: string) {
    setError(message);
    document.querySelector(".search-bar")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!req.origin.trim() || !req.destination.trim()) return fail("Tell me where you're leaving from and where you're headed.");
    if (nights < 1) return fail("Your return date needs to be after your departure date.");
    if (nights > 21) return fail("Trips are limited to 21 nights for now.");
    setError(null);
    const dietNote = diets.includes("Non veg")
      ? "Dietary: we eat non-veg - include restaurants with good non-veg dishes."
      : diets.length ? `Dietary: ${diets.join(", ").toLowerCase()} food only.` : "";
    onSubmit({
      ...req,
      origin: req.origin.trim(),
      destination: req.destination.trim(),
      work_location: req.persona === "business" ? req.work_location?.trim() || null : null,
      notes: [req.notes.trim(), dietNote].filter(Boolean).join(" "),
    });
  }

  const liveCount = health ? Object.values(health.providers).filter((v) => v === "live").length : 0;
  // Free hosting puts the server to sleep when idle; say so if the first answer is slow.
  const [slowWake, setSlowWake] = useState(false);
  useEffect(() => {
    if (health !== undefined) return;
    const t = setTimeout(() => setSlowWake(true), 4000);
    return () => clearTimeout(t);
  }, [health]);
  const hero = PHOTO_CREDITS.hero;

  return (
    <div className="landing">
      <header className="site-header">
        <div className="site-header-inner">
          <div className="brand">
            <div className="brand-mark"><Icon name="compass" size={19} /></div>
            Wayfinder
          </div>
          <div className="status-strip small">
            {health === undefined ? (
              <span className="tag">{slowWake ? "Waking up the server - free hosting sleeps when idle, about a minute…" : "Connecting to planner…"}</span>
            ) : health === null ? (
              <span className="tag" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
                <Icon name="alert" size={13} /> Backend offline - start it on :8000
              </span>
            ) : (
              <>
                <span className="tag tag-accent">
                  <Icon name="sparkles" size={12} />
                  {health.llm === "offline" ? "Heuristic mode (no LLM key)" : `Claude via ${health.llm.split(":")[0]}`}
                </span>
                {health.providers.ignav === "live" && <span className="tag tag-leaf">Live flight fares</span>}
                <span className="tag hide-compact">
                  {liveCount ? `${liveCount}/${Object.keys(health.providers).length} live data sources` : "Demo inventory"}
                </span>
              </>
            )}
          </div>
          <ThemeSwitch />
          <UserMenu />
        </div>
      </header>

      <section className="hero" style={{ backgroundImage: `url(${asset("/photos/hero.jpg")})` }}>
        <div className="hero-inner">
          <h1 className="hero-title">
            Your whole trip, planned by <span className="hero-mark">a team of AI agents</span>
          </h1>
          <p className="hero-sub">
            <span className="hero-sub-long">
              Tell the Orchestrator what you want. Its agents compare flights and IRCTC trains, stays from homestays to havelis,
              and the best sights and thalis, then hand back one bookable plan in rupees.
            </span>
            <span className="hero-sub-short">Flights and IRCTC trains, stays and day plans: one plan in rupees, tuned to how you travel.</span>
          </p>
        </div>
        <a className="photo-credit" href={hero.source} target="_blank" rel="noreferrer">
          {hero.title} · {hero.author} · {hero.license}
        </a>
      </section>

      <form className="landing-form" onSubmit={submit} noValidate>
        <div className="search-bar">
          <div className="field">
            <label htmlFor="origin">From</label>
            <div className="input-icon"><Icon name="pin" size={16} />
              <input id="origin" className="input" value={req.origin} onChange={(e) => set("origin", e.target.value)} placeholder="City or airport code" autoComplete="off" />
            </div>
          </div>
          <div className="field">
            <label htmlFor="destination">Where to?</label>
            <div className="input-icon"><Icon name="compass" size={16} />
              <input id="destination" className="input" value={req.destination} onChange={(e) => set("destination", e.target.value)} placeholder="Goa, Jaipur, Manali, Dubai…" autoComplete="off" />
            </div>
          </div>
          <div className="field">
            <label htmlFor="start">Depart</label>
            <input id="start" type="date" className="input" min={today} value={req.start_date}
              onChange={(e) => {
                const v = e.target.value;
                setReq((r) => {
                  const len = Math.max(1, nightsBetween(r.start_date, r.end_date));
                  const end = new Date(`${v}T12:00:00`);
                  end.setDate(end.getDate() + len);
                  return { ...r, start_date: v, end_date: r.end_date <= v ? isoDate(end) : r.end_date };
                });
              }} />
          </div>
          <div className="field">
            <label htmlFor="end">Return</label>
            <input id="end" type="date" className="input" min={req.start_date} value={req.end_date} onChange={(e) => set("end_date", e.target.value)} />
          </div>
          <button type="submit" className="btn btn-primary search-go" disabled={health === null}>
            Plan my trip <Icon name="arrow" size={15} />
          </button>
          {error && <div className="form-error search-error" role="alert"><Icon name="alert" size={16} /> {error}</div>}
        </div>

        <section className="block">
          <div className="block-inner">
            <div className="eyebrow">Popular destinations</div>
            <h2 className="section-heading">Choose the <b>destination</b> just right</h2>
            <div className="dest-grid">
              {POPULAR_DESTINATIONS.map((d) => {
                const photo = destinationPhoto(d);
                const credit = PHOTO_CREDITS[d.toLowerCase()];
                return (
                  <button type="button" key={d} className="dest-card" aria-pressed={req.destination === d} onClick={() => set("destination", d)}
                    title={credit ? `${credit.title} - photo: ${credit.author}, ${credit.license}` : d}>
                    {photo && <img src={photo} alt="" loading="lazy" />}
                    <span className="dest-plate">{d}</span>
                    {req.destination === d && <span className="dest-check"><Icon name="check" size={14} /></span>}
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        <section className="block block-tint">
          <div className="block-inner">
            <div className="eyebrow">Travel style</div>
            <h2 className="section-heading">How do you <b>travel</b>?</h2>
            <div className="persona-grid">
              {PERSONAS.map((p) => (
                <button type="button" key={p.key} className="persona" aria-pressed={req.persona === p.key} onClick={() => pickPersona(p.key)}>
                  <div className="persona-icon"><Icon name={PERSONA_ICON[p.key]} size={18} /></div>
                  <strong>{p.label}</strong>
                  <span>{p.blurb}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="block">
          <div className="block-inner">
            <div className="eyebrow">Travellers &amp; budget</div>
            <h2 className="section-heading">Who&apos;s going, and <b>how much</b>?</h2>
            <div className="party-grid">
              <div className="field">
                <label>Adults</label>
                <Stepper label="adults" value={req.adults} min={1} max={9} onChange={(v) => set("adults", v)} />
              </div>
              <div className="field">
                <label>Children</label>
                <Stepper label="children" value={req.children} min={0} max={8} onChange={(v) => set("children", v)} />
              </div>
              <div className="card budget-box">
                <div className="section-title" style={{ marginBottom: 4 }}>
                  <span className="label">Total budget</span>
                  <span className="small muted">
                    {nights > 0 ? `${nights} night${nights > 1 ? "s" : ""} · ≈ ${money(perNight)} per person per night` : ""}
                  </span>
                </div>
                <label className="budget-entry">
                  <span aria-hidden="true">₹</span>
                  <input id="budget" inputMode="numeric" autoComplete="off" aria-label="Total budget in rupees"
                    aria-describedby="budget-hint"
                    value={budgetText ?? req.budget.toLocaleString("en-IN")}
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => {
                      const digits = e.target.value.replace(/\D/g, "").slice(0, 8);
                      setBudgetText(digits ? Number(digits).toLocaleString("en-IN") : "");
                      const n = Number(digits);
                      if (n >= BUDGET_MIN && n <= BUDGET_MAX) { setBudgetTouched(true); set("budget", n); }
                    }}
                    onBlur={() => {
                      const n = Number((budgetText ?? "").replace(/\D/g, ""));
                      if (n) { setBudgetTouched(true); set("budget", Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, n))); }
                      setBudgetText(null);
                    }}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), (e.target as HTMLInputElement).blur())} />
                  <Icon name="edit" size={15} />
                </label>
                <div id="budget-hint" className={`tiny ${budgetOutOfRange ? "budget-warn" : "muted"}`}>
                  {budgetOutOfRange
                    ? `Enter between ${money(BUDGET_MIN)} and ${money(BUDGET_MAX)} - it will be adjusted when you leave the box.`
                    : "Type an exact amount or drag the slider."}
                </div>
                <input type="range" className="budget-range" min={0} max={1000} step={1} value={budgetToSlider(req.budget)} aria-label="Total budget"
                  aria-valuetext={money(req.budget)} style={{ ["--f" as string]: budgetToSlider(req.budget) / 1000 }}
                  onChange={(e) => { setBudgetTouched(true); setBudgetText(null); set("budget", sliderToBudget(Number(e.target.value))); }} />
                <div className="budget-ticks" aria-hidden="true">
                  {BUDGET_TICKS.map(([v, label]) => {
                    const f = budgetToSlider(v) / 1000;
                    // The thumb's centre travels from half a thumb in from each end, so offset labels to match.
                    return (
                      <span key={v}
                        style={{ left: `calc(${f * 100}% + ${(0.5 - f) * THUMB_PX}px)` }}>{label}</span>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="block block-tint">
          <div className="block-inner form-stack">
            <div>
              <div className="eyebrow">Make it yours</div>
              <h2 className="section-heading">What are you <b>into</b>?</h2>
              <div className="row wrap">
                {INTERESTS.map((i) => (
                  <button type="button" key={i} className="chip" aria-pressed={req.interests.includes(i)} onClick={() => toggleInterest(i)}>
                    {req.interests.includes(i) && <Icon name="check" size={13} />} {i}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="section-title"><h3>Food preferences</h3><span className="small muted">Meals are planned around these</span></div>
              <div className="row wrap">
                {DIETS.map((d) => (
                  <button type="button" key={d} className="chip" aria-pressed={diets.includes(d)}
                    onClick={() => setDiets((x) => toggleDiet(x, d))}>
                    {diets.includes(d) && <Icon name="check" size={13} />} {d}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid-2" style={{ alignItems: "end" }}>
              {req.persona === "business" ? (
                <div className="field">
                  <label htmlFor="work">Venue or office to stay near</label>
                  <input id="work" className="input" value={req.work_location ?? ""} onChange={(e) => set("work_location", e.target.value)} placeholder="e.g. Bharat Mandapam, BKC, Whitefield, HITEC City" />
                </div>
              ) : (
                <div />
              )}
              <label className="toggle">
                <input type="checkbox" checked={req.flexible_dates} onChange={(e) => set("flexible_dates", e.target.checked)} />
                My dates are flexible (±1 day) - find me savings
              </label>
            </div>

            <div className="field">
              <label htmlFor="notes">Anything else? Just say it</label>
              <textarea id="notes" className="input" rows={3} value={req.notes} onChange={(e) => set("notes", e.target.value)}
                placeholder="e.g. “Travelling with my parents - prefer AC 3-tier trains, a hotel with a pool, and no early-morning starts.”" />
            </div>

            <div className="submit-row">
              <span className="small muted">Your agents work in parallel - usually under a minute.</span>
              <button type="submit" className="btn btn-primary btn-lg" disabled={health === null}>
                Plan my trip <Icon name="arrow" size={16} />
              </button>
            </div>
          </div>
        </section>

        <section className="agents-band" aria-label="Your planning team">
          <div className="agents-band-inner">
            {AGENTS.map((a) => (
              <div className="band-item" key={a.key}>
                <span className="band-icon"><Icon name={AGENT_ICON[a.key]} size={22} /></span>
                <div>
                  <div className="band-title">{a.label} Agent</div>
                  <div className="band-text">{a.role}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </form>

      <footer className="site-footer">
        <p style={{ margin: "0 0 8px" }}>
          Privacy: we record which pages are visited, with the device, browser and a partly hidden IP address, to improve
          Wayfinder. Signed-in visits are linked to your account. Passwords are stored only as one-way hashes.{" "}
          <Link href="/privacy">Privacy Policy</Link>
        </p>
        Photos from Wikimedia Commons:{" "}
        {Object.entries(PHOTO_CREDITS).filter(([, c], i, all) => all.findIndex(([, x]) => x.source === c.source) === i).map(([k, c], i) => (
          <span key={k}>
            {i > 0 && " · "}
            <a href={c.source} target="_blank" rel="noreferrer">{c.title}</a> ({c.author}, {c.license})
          </span>
        ))}
      </footer>
    </div>
  );
}
