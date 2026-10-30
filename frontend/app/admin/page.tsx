"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { Icon, type IconName } from "@/components/Icon";
import ThemeSwitch from "@/components/ThemeSwitch";
import UserMenu from "@/components/UserMenu";
import {
  adminCustomers, adminSummary, adminTrips, adminVisits, downloadCsv,
  type CustomerRow, type Summary, type TripRow, type VisitRow,
} from "@/lib/admin";
import { ApiError } from "@/lib/auth";
import { PERSONAS, money } from "@/lib/format";
import { pageUrl } from "@/lib/site";

type Tab = "overview" | "visits" | "customers" | "trips";

const IST = "Asia/Kolkata";
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
const dayLabel = (d: string, long = false) =>
  new Date(`${d}T12:00:00+05:30`).toLocaleDateString("en-IN", long ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" });
const personaLabel = (k: string) => PERSONAS.find((p) => p.key === k)?.label ?? k;
const num = (n: number) => n.toLocaleString("en-IN");
const count = (n: number, one: string, many: string) => `${num(n)} ${n === 1 ? one : many}`;

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

// ---------- overview pieces ----------
function Kpi({ icon, label, value, sub }: { icon: IconName; label: string; value: number; sub?: string }) {
  return (
    <div className="card kpi">
      <div className="kpi-head"><Icon name={icon} size={16} /> {label}</div>
      <div className="kpi-value">{num(value)}</div>
      {sub && <div className="tiny muted">{sub}</div>}
    </div>
  );
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const pow = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow * 4 >= v)! * pow;
  return step * 4;
}

/** Daily visitors and page views: two counts on one shared axis, with a hover crosshair. */
function TrendChart({ series }: { series: Summary["series"] }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const H = 240, M = { l: 40, r: 78, t: 14, b: 28 };
  const iw = width - M.l - M.r, ih = H - M.t - M.b;
  const yMax = niceMax(Math.max(1, ...series.map((d) => d.views)));
  const step = series.length > 1 ? iw / (series.length - 1) : iw;
  const x = (i: number) => M.l + i * step;
  const y = (v: number) => M.t + ih - (v / yMax) * ih;
  const path = (key: "views" | "visitors") => series.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join("");
  const ticks = [0, 1, 2, 3, 4].map((k) => (yMax / 4) * k);
  const every = Math.max(1, Math.ceil(series.length / Math.max(3, Math.floor(iw / 90))));
  const last = series.length - 1;
  const lines = [
    { key: "visitors" as const, label: "Visitors", color: "var(--viz-1)" },
    { key: "views" as const, label: "Page views", color: "var(--viz-2)" },
  ];
  // Keep the two end labels from overlapping.
  const vy0 = y(series[last]?.visitors ?? 0), py0 = y(series[last]?.views ?? 0);
  let yv = vy0, yp = py0;
  if (Math.abs(vy0 - py0) < 14) {
    const mid = (vy0 + py0) / 2, visitorsLower = vy0 >= py0;
    yv = mid + (visitorsLower ? 7 : -7);
    yp = mid + (visitorsLower ? -7 : 7);
  }
  const h = hover !== null ? series[hover] : null;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const i = Math.round((e.clientX - r.left) / step);
    setHover(Math.max(0, Math.min(last, i)));
  };

  const total = series.reduce((a, d) => ({ views: a.views + d.views, visitors: a.visitors + d.visitors }), { views: 0, visitors: 0 });
  return (
    <div className="chart" ref={box}>
      <div className="chart-legend" aria-hidden="true">
        {lines.map((l) => <span key={l.key}><i style={{ background: l.color }} />{l.label}</span>)}
      </div>
      <svg width={width} height={H} role="img"
        aria-label={`Daily visitors and page views for the last ${series.length} days: ${num(total.visitors)} visitor-days and ${num(total.views)} page views in total.`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={M.l + iw} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={M.l - 8} y={y(t) + 4} textAnchor="end" className="chart-axis">{num(t)}</text>
          </g>
        ))}
        {series.map((d, i) => (i % every === 0 || i === last) && (i === last || last - i >= every * 0.6) ? (
          <text key={d.date} x={x(i)} y={H - 8} textAnchor="middle" className="chart-axis">{dayLabel(d.date)}</text>
        ) : null)}
        {lines.map((l) => <path key={l.key} d={path(l.key)} fill="none" stroke={l.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
        <text x={x(last) + 8} y={yv + 4} className="chart-end">Visitors {num(series[last]?.visitors ?? 0)}</text>
        <text x={x(last) + 8} y={yp + 4} className="chart-end">Views {num(series[last]?.views ?? 0)}</text>
        {h && (
          <g pointerEvents="none">
            <line x1={x(hover!)} x2={x(hover!)} y1={M.t} y2={M.t + ih} className="chart-crosshair" />
            {lines.map((l) => (
              <circle key={l.key} cx={x(hover!)} cy={y(h[l.key])} r={4.5} fill={l.color} stroke="var(--surface)" strokeWidth={2} />
            ))}
          </g>
        )}
        <rect x={M.l - step / 2} y={M.t} width={iw + step} height={ih} fill="transparent"
          onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {h && (
        <div className="chart-tip" style={{ left: Math.min(Math.max(x(hover!) - 80, 0), width - 170), top: 34 }}>
          <b>{dayLabel(h.date, true)}</b>
          {lines.map((l) => (
            <div key={l.key} className="chart-tip-row"><i style={{ background: l.color }} />{l.label}<span>{num(h[l.key])}</span></div>
          ))}
        </div>
      )}
      <details className="chart-table">
        <summary>Show as table</summary>
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr><th>Date</th><th className="num">Visitors</th><th className="num">Page views</th></tr></thead>
            <tbody>{[...series].reverse().map((d) => <tr key={d.date}><td>{dayLabel(d.date, true)}</td><td className="num">{num(d.visitors)}</td><td className="num">{num(d.views)}</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/** Ranked list with a magnitude bar (one hue: it's the same measure for every row). */
function BarList({ title, rows, empty, format = (s: string) => s }: {
  title: string; rows: [string, number][]; empty: string; format?: (s: string) => string;
}) {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return (
    <div className="card bar-card">
      <h3>{title}</h3>
      {rows.length ? (
        <ul className="bar-list">
          {rows.map(([k, v]) => (
            <li key={k} title={`${format(k)}: ${num(v)}`}>
              <div className="bar-row"><span className="one-line">{format(k)}</span><b>{num(v)}</b></div>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / max) * 100}%` }} /></div>
            </li>
          ))}
        </ul>
      ) : <p className="small muted">{empty}</p>}
    </div>
  );
}

function Overview() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setData(null);
    adminSummary(days).then(setData).catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the overview."));
  }, [days]);
  if (error) return <div className="form-error" role="alert"><Icon name="alert" size={16} /> {error}</div>;
  if (!data) return <div className="kpi-grid">{Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton" style={{ height: 104 }} />)}</div>;
  const k = data.kpis;
  const pageName = (p: string) => ({ "/": "Home / planner", "/login": "Log in", "/signup": "Sign up", "/profile": "Profile" } as Record<string, string>)[p] ?? p;
  return (
    <div className="admin-stack">
      <div className="kpi-grid">
        <Kpi icon="users" label="Visitors today" value={k.visitors_today} sub={`${num(k.views_today)} page views`} />
        <Kpi icon="compass" label="Visitors, last 7 days" value={k.visitors_7d} sub={`${num(k.views_7d)} page views · ${num(k.signed_in_visitors_7d)} signed in`} />
        <Kpi icon="user" label="Customers" value={k.customers} sub={`+${num(k.new_customers_7d)} this week · ${num(k.google_customers)} via Google`} />
        <Kpi icon="bookmark" label="Trips saved" value={k.trips} sub={`+${num(k.trips_7d)} this week`} />
      </div>
      <div className="card chart-card">
        <div className="chart-head">
          <h3>Visitors and page views</h3>
          <div className="seg" role="group" aria-label="Time range">
            {[7, 30, 90].map((d) => <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{d} days</button>)}
          </div>
        </div>
        <TrendChart series={data.series} />
      </div>
      <div className="bar-grid">
        <BarList title="Top pages" rows={data.top_pages} empty="No visits yet." format={pageName} />
        <BarList title="Popular destinations" rows={data.destinations} empty="No trips saved yet." />
        <BarList title="Devices" rows={data.devices} empty="No visits yet." />
        <BarList title="Browsers" rows={data.browsers} empty="No visits yet." />
        <BarList title="Came from" rows={data.referrers} empty="No visits from other websites yet." />
      </div>
    </div>
  );
}

// ---------- tables ----------
function Toolbar({ q, setQ, placeholder, count, onExport }: { q: string; setQ: (v: string) => void; placeholder: string; count: string; onExport: () => void }) {
  return (
    <div className="admin-toolbar">
      <div className="input-icon grow">
        <Icon name="search" size={16} />
        <input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
      </div>
      <span className="small muted">{count}</span>
      <button className="btn btn-sm" onClick={onExport}><Icon name="download" size={14} /> Export CSV</button>
    </div>
  );
}

function CustomerCell({ c }: { c: { name: string; email: string } | null }) {
  if (!c) return <span className="muted">Anonymous</span>;
  return <span className="cell-person"><b>{c.name}</b><span className="tiny muted">{c.email}</span></span>;
}

function Visits() {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [page, setPage] = useState(0);
  const [data, setData] = useState<{ total: number; rows: VisitRow[] } | null>(null);
  const PAGE = 50;
  useEffect(() => setPage(0), [dq]);
  useEffect(() => {
    adminVisits(dq, PAGE, page * PAGE).then(setData).catch(() => setData({ total: 0, rows: [] }));
  }, [dq, page]);

  async function exportAll() {
    const all: VisitRow[] = [];
    for (let off = 0; off < 10000; off += 200) {
      const r = await adminVisits(dq, 200, off);
      all.push(...r.rows);
      if (all.length >= r.total) break;
    }
    downloadCsv("wayfinder-visits.csv", ["Time (IST)", "Customer", "Email", "Visitor ID", "Page", "Came from", "Device", "Browser", "OS", "IP (masked)"],
      all.map((v) => [when(v.time), v.customer?.name ?? "Anonymous", v.customer?.email ?? "", v.visitor, v.path, v.referrer, v.device, v.browser, v.os, v.ip]));
  }

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1;
  return (
    <div className="card table-card">
      <Toolbar q={q} setQ={setQ} placeholder="Search page, customer, browser, device…" count={data ? count(data.total, "visit", "visits") : "Loading…"} onExport={exportAll} />
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Time (IST)</th><th>Visitor</th><th>Page</th><th>Device</th><th>Browser · OS</th><th>Came from</th><th>IP</th></tr></thead>
          <tbody>
            {data?.rows.map((v) => (
              <tr key={v.id}>
                <td className="nowrap">{when(v.time)}</td>
                <td>{v.customer ? <CustomerCell c={v.customer} /> : <span className="muted">Anonymous <span className="tiny">#{v.visitor}</span></span>}</td>
                <td><code>{v.path}</code></td>
                <td>{v.device}</td>
                <td className="nowrap">{v.browser} · {v.os}</td>
                <td>{v.referrer || <span className="muted">Direct</span>}</td>
                <td className="nowrap muted">{v.ip || "—"}</td>
              </tr>
            ))}
            {data && !data.rows.length && <tr><td colSpan={7} className="empty-cell">No visits{dq ? " match your search" : " recorded yet"}.</td></tr>}
          </tbody>
        </table>
      </div>
      {data && data.total > PAGE && (
        <div className="pager">
          <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Newer</button>
          <span className="small muted">Page {page + 1} of {pages}</span>
          <button className="btn btn-sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Older</button>
        </div>
      )}
    </div>
  );
}

function Customers() {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [data, setData] = useState<{ total: number; rows: CustomerRow[] } | null>(null);
  useEffect(() => {
    adminCustomers(dq).then(setData).catch(() => setData({ total: 0, rows: [] }));
  }, [dq]);

  const exportAll = () => data && downloadCsv("wayfinder-customers.csv",
    ["Name", "Email", "Phone", "Home city", "Travel style", "Usual budget (INR)", "Diet", "Interests", "About", "Sign-in", "Password", "Trips", "Visits", "Last seen (IST)", "Joined (IST)"],
    data.rows.map((c) => [c.name, c.email, c.phone, c.home_city, personaLabel(c.persona), c.budget, c.diets.join("; "), c.interests.join("; "), c.bio,
      c.sign_in.join(" + "), c.password ? "(hidden)" : "none - Google", c.trips, c.visits, when(c.last_seen), when(c.created_at)]));

  return (
    <div className="card table-card">
      <Toolbar q={q} setQ={setQ} placeholder="Search name, email, phone, city…" count={data ? count(data.total, "customer", "customers") : "Loading…"} onExport={() => exportAll()} />
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Customer</th><th>Phone</th><th>Home city</th><th>Travel style</th><th className="num">Usual budget</th><th>Diet · interests</th>
              <th>Sign-in</th><th>Password</th><th className="num">Trips</th><th className="num">Visits</th><th>Last seen</th><th>Joined</th></tr>
          </thead>
          <tbody>
            {data?.rows.map((c) => (
              <tr key={c.id}>
                <td><CustomerCell c={c} />{c.is_admin && <span className="tag tag-accent" style={{ marginTop: 4 }}>Admin</span>}</td>
                <td className="nowrap">{c.phone || <span className="muted">—</span>}</td>
                <td>{c.home_city || <span className="muted">—</span>}</td>
                <td className="nowrap">{personaLabel(c.persona)}</td>
                <td className="num nowrap">{c.budget ? money(c.budget) : <span className="muted">—</span>}</td>
                <td className="wide-cell">{[...c.diets, ...c.interests].join(", ") || <span className="muted">—</span>}</td>
                <td className="nowrap">{c.sign_in.map((s) => <span key={s} className={`tag ${s === "google" ? "tag-leaf" : ""}`} style={{ marginRight: 4 }}>{s === "google" ? "Google" : "Email"}</span>)}</td>
                <td className="nowrap">
                  {c.password ? <span className="pw-mask" title="Stored as a one-way hash - nobody can see it">{c.password}</span> : <span className="muted">None (Google)</span>}
                </td>
                <td className="num">{num(c.trips)}</td>
                <td className="num">{num(c.visits)}</td>
                <td className="nowrap">{when(c.last_seen)}</td>
                <td className="nowrap">{when(c.created_at)}</td>
              </tr>
            ))}
            {data && !data.rows.length && <tr><td colSpan={12} className="empty-cell">No customers{dq ? " match your search" : " yet"}.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="tiny muted table-note"><Icon name="lock" size={12} /> Passwords are stored as one-way hashes. Nobody, including admins, can see them; they show as dots here.</p>
    </div>
  );
}

function Trips() {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const [data, setData] = useState<{ total: number; rows: TripRow[] } | null>(null);
  useEffect(() => {
    adminTrips(dq).then(setData).catch(() => setData({ total: 0, rows: [] }));
  }, [dq]);
  const exportAll = () => data && downloadCsv("wayfinder-trips.csv",
    ["Customer", "Email", "Trip", "Destination", "From date", "To date", "Travel style", "Estimated total (INR)", "Version", "Saved (IST)", "Updated (IST)"],
    data.rows.map((t) => [t.customer.name, t.customer.email, t.title, t.destination, t.start_date, t.end_date, personaLabel(t.persona), t.total, t.version, when(t.created_at), when(t.updated_at)]));
  return (
    <div className="card table-card">
      <Toolbar q={q} setQ={setQ} placeholder="Search trip, destination, customer…" count={data ? count(data.total, "trip", "trips") : "Loading…"} onExport={() => exportAll()} />
      <div className="table-wrap">
        <table className="data-table">
          <thead><tr><th>Customer</th><th>Trip</th><th>Dates</th><th>Travel style</th><th className="num">Estimated total</th><th className="num">Version</th><th>Last updated</th></tr></thead>
          <tbody>
            {data?.rows.map((t) => (
              <tr key={t.id}>
                <td><CustomerCell c={t.customer} /></td>
                <td><b>{t.title}</b></td>
                <td className="nowrap">{dayLabel(t.start_date)} – {dayLabel(t.end_date)}</td>
                <td className="nowrap">{personaLabel(t.persona)}</td>
                <td className="num nowrap">{money(t.total)}</td>
                <td className="num">{t.version}</td>
                <td className="nowrap">{when(t.updated_at)}</td>
              </tr>
            ))}
            {data && !data.rows.length && <tr><td colSpan={7} className="empty-cell">No trips{dq ? " match your search" : " saved yet"}.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- page ----------
export default function AdminPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t === "visits" || t === "customers" || t === "trips") setTab(t);
  }, []);
  useEffect(() => {
    if (!loading && !user) router.replace("/login?next=/admin");
  }, [loading, user, router]);

  const go = useCallback((t: Tab) => {
    setTab(t);
    window.history.replaceState(null, "", pageUrl("/admin", t === "overview" ? "" : `?tab=${t}`));
  }, []);
  const tabs = useMemo(() => [
    { key: "overview" as Tab, label: "Overview", icon: "sparkles" as IconName },
    { key: "visits" as Tab, label: "Visits", icon: "compass" as IconName },
    { key: "customers" as Tab, label: "Customers", icon: "users" as IconName },
    { key: "trips" as Tab, label: "Trips", icon: "bookmark" as IconName },
  ], []);

  if (loading || !user) return <div className="profile-page"><div className="profile-inner" style={{ paddingTop: 40 }}><div className="skeleton" style={{ height: 160 }} /></div></div>;

  return (
    <div className="profile-page admin-page">
      <header className="profile-topbar">
        <Link href="/" className="brand"><span className="brand-mark"><Icon name="compass" size={19} /></span> Wayfinder</Link>
        <span className="tag tag-accent">Admin</span>
        <div className="row" style={{ marginLeft: "auto", gap: 10 }}>
          <ThemeSwitch />
          <UserMenu compact />
        </div>
      </header>
      {!user.is_admin ? (
        <div className="profile-inner" style={{ paddingTop: 48 }}>
          <div className="card empty-state">
            <Icon name="lock" size={28} />
            <h3>Admins only</h3>
            <p className="muted">Your account doesn&apos;t have access to the admin panel.</p>
            <Link href="/" className="btn btn-primary">Back to the planner</Link>
          </div>
        </div>
      ) : (
        <div className="admin-inner">
          <div className="admin-title">
            <div className="eyebrow">Admin panel</div>
            <h1 className="section-heading" style={{ marginBottom: 0 }}>Visitors &amp; <b>customers</b></h1>
          </div>
          <nav className="tabs profile-tabs" role="tablist" aria-label="Admin sections">
            {tabs.map((t) => (
              <button key={t.key} role="tab" className="tab" aria-selected={tab === t.key} onClick={() => go(t.key)}><Icon name={t.icon} size={15} /> {t.label}</button>
            ))}
          </nav>
          {tab === "overview" && <Overview />}
          {tab === "visits" && <Visits />}
          {tab === "customers" && <Customers />}
          {tab === "trips" && <Trips />}
        </div>
      )}
    </div>
  );
}
