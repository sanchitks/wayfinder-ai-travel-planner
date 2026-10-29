"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRef, useState } from "react";
import { AGENTS, DAY_COLORS, PERSONAS, money, nightsBetween, shortDate } from "@/lib/format";
import { PHOTO_CREDITS, destinationPhoto } from "@/lib/photos";
import type { AgentName, AgentState, Itinerary, TripRequest } from "@/lib/types";
import Days from "./Days";
import { Icon, type IconName } from "./Icon";
import { AGENT_ICON } from "./Onboarding";
import { FlightCard, HotelCard, Stars } from "./Options";

const TripMap = dynamic(() => import("./TripMap"), {
  ssr: false,
  loading: () => <div className="map skeleton" />,
});

type Tab = "overview" | "days" | "flights" | "stays" | "map";

/** Header photo: our bundled destination photo, else the trip's most notable sight that has one. */
function bannerPhoto(it: Itinerary): { src: string; href: string; label: string } | null {
  const local = destinationPhoto(it.request.destination);
  if (local) {
    const c = PHOTO_CREDITS[it.request.destination.split(",")[0].trim().toLowerCase()];
    return { src: local, href: c.source, label: `${c.title} · ${c.author} · ${c.license}` };
  }
  const sight = it.days
    .flatMap((d) => d.activities)
    .filter((a) => a.kind === "activity" && a.place.image_url)
    .sort((a, b) => b.place.popularity - a.place.popularity)[0];
  if (sight) return { src: sight.place.image_url, href: sight.place.url, label: `${sight.place.name} · photo via Wikipedia` };
  return null;
}

function BudgetMeter({ it }: { it: Itinerary }) {
  const c = it.costs;
  const scale = Math.max(c.total, c.budget) || 1;
  const parts = [
    { key: "flights", label: "Travel", v: c.flights },
    { key: "lodging", label: "Lodging", v: c.lodging },
    { key: "activities", label: "Activities", v: c.activities },
    { key: "food", label: "Dining", v: c.food },
  ];
  const diff = c.budget - c.total;
  return (
    <section className="card budget-card" aria-label="Budget">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div className="row" style={{ alignItems: "baseline", gap: 10 }}>
          <span className="display" style={{ fontSize: 24 }}>{money(c.total, c.currency)}</span>
          <span className="small muted">estimated of {money(c.budget, c.currency)} budget</span>
        </div>
        <span className={`tag ${diff >= 0 ? "tag-leaf" : "tag-sun"}`}>
          {diff >= 0 ? `${money(diff, c.currency)} under budget` : `${money(-diff, c.currency)} over budget`}
        </span>
      </div>
      <div className="budget-bar" role="img" aria-label={`Spending ${money(c.total)} of ${money(c.budget)}`}>
        {parts.map((p) => (
          <div key={p.key} style={{ width: `${(p.v / scale) * 100}%`, background: `var(--c-${p.key})` }} title={`${p.label}: ${money(p.v)}`} />
        ))}
        <span className="budget-marker" style={{ left: `calc(${(c.budget / scale) * 100}% - 1px)` }} title="Budget" />
      </div>
      <div className="legend">
        {parts.map((p) => (
          <span key={p.key}><i style={{ background: `var(--c-${p.key})` }} />{p.label} {money(p.v, c.currency)}</span>
        ))}
      </div>
    </section>
  );
}

function Planning({ agents, request }: { agents: Record<AgentName, AgentState>; request: TripRequest | null }) {
  return (
    <div className="planning">
      <div>
        <div className="label" style={{ marginBottom: 6 }}>Building your itinerary</div>
        <h2 className="display plan-title">{request?.destination || "Your trip"}</h2>
        <p className="muted" style={{ margin: "6px 0 0" }}>Your agents are working in parallel. Results appear here the moment they&apos;re compiled.</p>
      </div>
      <div className="planning-steps">
        {AGENTS.map((a) => {
          const s = agents[a.key];
          return (
            <div key={a.key} className="card planning-step" style={{ ["--agent" as string]: `var(--a-${a.key})` }}>
              <div className="agent-dot" style={{ background: `var(--a-${a.key})` }}><Icon name={AGENT_ICON[a.key]} size={18} /></div>
              <div className="grow">
                <div style={{ fontWeight: 650 }}>{a.label} Agent</div>
                <ul className="log">
                  {(s.log.length ? s.log.slice(-3) : ["Waiting for the brief…"]).map((l, i) => <li key={i}>{l}</li>)}
                </ul>
              </div>
              {s.status === "working" ? <div className="spinner" aria-label="working" />
                : s.status === "done" ? <Icon name="check" size={20} style={{ color: "var(--accent)" }} />
                : s.status === "error" ? <Icon name="alert" size={20} style={{ color: "var(--danger)" }} />
                : <span className="tiny muted">queued</span>}
            </div>
          );
        })}
      </div>
      <div className="skeleton" style={{ height: 120 }} />
    </div>
  );
}

export default function ItineraryPanel({
  itinerary, agents, busy, request, onSelect, account,
}: {
  itinerary: Itinerary | null;
  agents: Record<AgentName, AgentState>;
  busy: boolean;
  request: TripRequest | null;
  onSelect: (kind: "flight" | "hotel", id: string) => void;
  /** Save state: signed-in trips save automatically; signed-out users get a "log in to save" link. */
  account?: { signedIn: boolean; saved: boolean; onLoginToSave: () => void };
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const tabsRef = useRef<HTMLElement>(null);

  // On short screens the tab bar can sit near the bottom; bring the chosen section into view.
  const openTab = (t: Tab) => {
    setTab(t);
    const bar = tabsRef.current;
    if (bar && bar.getBoundingClientRect().top > window.innerHeight * 0.45) bar.scrollIntoView({ block: "start", behavior: "smooth" });
  };

  if (!itinerary) {
    return <section className="plan" aria-label="Itinerary"><Planning agents={agents} request={request} /></section>;
  }

  const it = itinerary;
  const req = it.request;
  const nights = Math.max(1, nightsBetween(req.start_date, req.end_date));
  const party = req.adults + 0.5 * req.children;
  const persona = PERSONAS.find((p) => p.key === req.persona)!;
  const sources = Object.entries(it.data_sources);
  const allDemo = sources.every(([, v]) => /demo|sample/.test(v));
  const stopCount = it.days.reduce((n, d) => n + d.activities.length, 0);
  const banner = bannerPhoto(it);

  const tabs: { key: Tab; label: string; icon: IconName; count?: number }[] = [
    { key: "overview", label: "Overview", icon: "sparkles" },
    { key: "days", label: "Day by day", icon: "calendar", count: it.days.length },
    { key: "flights", label: it.flight?.mode === "train" || it.flight_alternatives.some((f) => f.mode === "train") ? "Flights & trains" : "Flights", icon: it.flight?.mode === "train" ? "train" : "plane", count: 1 + it.flight_alternatives.length },
    { key: "stays", label: "Stays", icon: "bed", count: (it.hotel ? 1 : 0) + it.hotel_alternatives.length },
    { key: "map", label: "Map", icon: "map" },
  ];

  const goDay = (n: number) => {
    setTab("days");
    setTimeout(() => document.getElementById(`day-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  return (
    <section className="plan" aria-label="Itinerary" aria-busy={busy}>
      {busy && <div className="updating-bar" aria-hidden="true" />}
      <div className="plan-inner" style={{ opacity: busy ? 0.72 : 1, transition: "opacity .2s" }}>
        <header className={`plan-header plan-banner${banner ? " has-photo" : ""}`}
          style={banner ? { backgroundImage: `url("${banner.src}")` } : undefined}>
          {banner && (
            <a className="photo-credit" href={banner.href} target="_blank" rel="noreferrer">{banner.label}</a>
          )}
          <div>
            <div className="row wrap" style={{ marginBottom: 6 }}>
              <span className="tag tag-leaf">{persona.label}</span>
              <span className="tag">Version {it.version}</span>
              {account?.saved && (
                <Link href="/profile?tab=trips" className="tag tag-leaf save-tag" title="Open your saved trips">
                  <Icon name="check" size={12} /> Saved to your trips
                </Link>
              )}
              {account && !account.signedIn && (
                <button type="button" className="tag save-tag save-cta" onClick={account.onLoginToSave}>
                  <Icon name="bookmark" size={12} /> Log in to save this trip
                </button>
              )}
              {allDemo && <span className="tag tag-sun" title="Add API keys in backend/.env for live inventory">Sample inventory</span>}
              {it.data_sources.hotels === "openstreetmap" && (
                <span className="tag tag-leaf" title="Real properties from OpenStreetMap; prices are estimates">
                  <Icon name="bed" size={12} /> Real hotels
                </span>
              )}
              {(it.data_sources.flights ?? "").includes("ignav") && (
                <span className="tag tag-leaf" title="Real fares from Ignav, India market, in INR">
                  <Icon name="plane" size={12} /> Live flight fares
                </span>
              )}
              {it.data_sources.hotels === "tripadvisor" && (
                <span className="tag tag-leaf" title="Real hotels from TripAdvisor with live prices from Booking.com, Agoda, Trip.com and more">
                  <Icon name="bed" size={12} /> Live hotel prices
                </span>
              )}
              {it.data_sources.hotels === "booking.com" && (
                <span className="tag tag-leaf"><Icon name="bed" size={12} /> Live hotel prices</span>
              )}
            </div>
            <h1 className="display plan-title">{req.origin} → {req.destination}</h1>
            <div className="meta" style={{ marginTop: 8 }}>
              <span><Icon name="calendar" size={15} />{shortDate(req.start_date)} – {shortDate(req.end_date)} · {nights} nights</span>
              <span><Icon name="users" size={15} />{req.adults} adult{req.adults > 1 ? "s" : ""}{req.children ? `, ${req.children} child${req.children > 1 ? "ren" : ""}` : ""}</span>
              <span><Icon name="route" size={15} />{stopCount} stops planned</span>
            </div>
          </div>
        </header>

        <BudgetMeter it={it} />

        <nav ref={tabsRef} className="tabs" role="tablist" aria-label="Itinerary sections">
          {tabs.map((t) => (
            <button key={t.key} role="tab" className="tab" aria-selected={tab === t.key} onClick={() => openTab(t.key)}>
              <Icon name={t.icon} size={15} /> {t.label}
              {t.count !== undefined && <span className="count">{t.count}</span>}
            </button>
          ))}
        </nav>

        {tab === "overview" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="overview-grid">
              <div className="card summary-card">
                <div className="label">Trip summary</div>
                <p>{it.summary}</p>
                {it.highlights.length > 0 && (
                  <ul className="highlights">
                    {it.highlights.map((h, i) => <li key={i}><Icon name="check" size={16} />{h}</li>)}
                  </ul>
                )}
              </div>
              <div className="card mini-days">
                <div className="label" style={{ padding: "0 8px" }}>Your days</div>
                {it.days.map((d) => (
                  <button key={d.day} className="mini-day" onClick={() => goDay(d.day)}>
                    <div className="day-badge" style={{ background: DAY_COLORS[(d.day - 1) % DAY_COLORS.length] }}>{d.day}</div>
                    <div className="grow">
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{d.theme}</div>
                      <div className="tiny muted">{shortDate(d.date)} · {d.activities.length} stop{d.activities.length === 1 ? "" : "s"}</div>
                    </div>
                    <Icon name="arrow" size={14} className="muted" />
                  </button>
                ))}
              </div>
            </div>
            {it.flight && <FlightCard f={it.flight} selected />}
            {it.hotel && <HotelCard h={it.hotel} nights={nights} selected />}
            {sources.length > 0 && (
              <div className="sources">
                <Icon name="layers" size={13} /> Data:
                {sources.map(([k, v]) => <span key={k} className="tag">{k}: {v === "demo" ? "sample" : v}</span>)}
              </div>
            )}
          </div>
        )}

        {tab === "days" && <Days days={it.days} party={party} />}

        {tab === "flights" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {it.flight ? <FlightCard f={it.flight} selected /> : <div className="card option">No flights or trains found for these dates.</div>}
            {it.flight_alternatives.length > 0 && (
              <>
                <div className="section-label">Alternatives the Logistics agent considered</div>
                <div className="alt-list">
                  {it.flight_alternatives.map((f) => (
                    <FlightCard key={f.id} f={f} compact disabled={busy} onChoose={() => onSelect("flight", f.id)} />
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {tab === "stays" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {it.hotel ? <HotelCard h={it.hotel} nights={nights} selected /> : <div className="card option">No stays found.</div>}
            {it.hotel_alternatives.length > 0 && (
              <>
                <div className="section-label">Other options the Accommodation agent considered</div>
                <div className="hotel-grid">
                  {it.hotel_alternatives.map((h) => (
                    <HotelCard key={h.id} h={h} nights={nights} disabled={busy} onChoose={() => onSelect("hotel", h.id)} />
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {tab === "map" && <TripMap itinerary={it} />}

        {it.hotel && tab !== "stays" && tab !== "overview" && (
          <div className="small muted row" style={{ gap: 6 }}>
            <Icon name="bed" size={14} /> Staying at {it.hotel.name} <Stars n={it.hotel.stars} />
          </div>
        )}
      </div>
    </section>
  );
}
