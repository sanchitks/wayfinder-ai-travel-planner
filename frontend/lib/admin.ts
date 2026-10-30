import { API_URL } from "./api";
import { ApiError } from "./auth";
import { authHeaders, visitorHeaders } from "./site";

export interface CustomerRef { id: number; name: string; email: string }

export interface Summary {
  days: number;
  kpis: {
    visitors_today: number; views_today: number; visitors_7d: number; views_7d: number; signed_in_visitors_7d: number;
    customers: number; new_customers_7d: number; google_customers: number; trips: number; trips_7d: number;
  };
  series: { date: string; views: number; visitors: number }[];
  top_pages: [string, number][];
  devices: [string, number][];
  browsers: [string, number][];
  referrers: [string, number][];
  destinations: [string, number][];
}

export interface VisitRow {
  id: number; time: string; visitor: string; customer: CustomerRef | null;
  path: string; referrer: string; browser: string; os: string; device: string; ip: string;
}

export interface CustomerRow {
  id: number; name: string; email: string; phone: string; home_city: string; persona: string; budget: number | null;
  diets: string[]; interests: string[]; bio: string;
  /** "••••••••" when a password is set, "" otherwise. The real password/hash never leaves the server. */
  password: string;
  sign_in: string[]; is_admin: boolean; trips: number; visits: number; last_seen: string | null; created_at: string;
}

export interface TripRow {
  id: string; customer: CustomerRef; title: string; destination: string; start_date: string; end_date: string;
  persona: string; total: number; version: number; created_at: string; updated_at: string;
}

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}${qs ? `?${qs}` : ""}`, { credentials: "include", headers: authHeaders() });
  } catch {
    throw new ApiError("Can't reach the server.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : "Something went wrong.", res.status);
  return data as T;
}

export const adminSummary = (days = 30) => get<Summary>("/api/admin/summary", { days });
export const adminVisits = (q = "", limit = 50, offset = 0) => get<{ total: number; rows: VisitRow[] }>("/api/admin/visits", { q, limit, offset });
export const adminCustomers = (q = "") => get<{ total: number; rows: CustomerRow[] }>("/api/admin/customers", { q });
export const adminTrips = (q = "") => get<{ total: number; rows: TripRow[] }>("/api/admin/trips", { q });

/** Record a page view (fire-and-forget; never blocks or breaks the page). */
export function recordVisit(path: string) {
  try {
    void fetch(`${API_URL}/api/visits`, {
      method: "POST", credentials: "include", keepalive: true,
      headers: { "Content-Type": "application/json", ...authHeaders(), ...visitorHeaders() },
      body: JSON.stringify({ path, referrer: document.referrer || "" }),
    }).catch(() => {});
  } catch {}
}

/** Download rows as a CSV file (opens in Excel / Google Sheets). */
export function downloadCsv(filename: string, header: string[], rows: (string | number | null)[][]) {
  const cell = (v: string | number | null) => {
    const s = v === null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = "﻿" + [header, ...rows].map((r) => r.map(cell).join(",")).join("\r\n"); // BOM so Excel reads ₹ correctly
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}
