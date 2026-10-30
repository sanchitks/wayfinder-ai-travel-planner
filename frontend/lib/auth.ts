import { API_URL } from "./api";
import { authHeaders, setToken, TOKEN_MODE } from "./site";
import type { Itinerary, Persona } from "./types";

export interface User {
  id: number;
  email: string;
  name: string;
  phone: string;
  home_city: string;
  persona: Persona;
  budget: number | null;
  diets: string[];
  interests: string[];
  bio: string;
  created_at: string;
  trip_count: number;
  /** Profile photo (from Google), or "". */
  avatar_url: string;
  /** False for accounts created with Google that haven't set a password yet. */
  has_password: boolean;
  linked_providers: string[];
  /** Can open the admin panel (/admin). */
  is_admin: boolean;
}

export type ProfileInput = Pick<User, "name" | "phone" | "home_city" | "persona" | "budget" | "diets" | "interests" | "bio">;

export interface TripSummary {
  id: string;
  title: string;
  destination: string;
  start_date: string;
  end_date: string;
  persona: Persona;
  total: number;
  version: number;
  image: string;
  created_at: string;
  updated_at: string;
}

/** An API error; `fields` maps form field names to messages for 422 validation errors. */
export class ApiError extends Error {
  constructor(message: string, public status: number, public fields: Record<string, string> = {}) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      credentials: "include", // the HttpOnly login cookie (local); token mode uses the header instead
      headers: { ...authHeaders(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(TOKEN_MODE ? "Can't reach the server. It may be waking up - please try again in a minute." : "Can't reach the server. Is the backend running on port 8000?", 0);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const fields: Record<string, string> = {};
    let message = typeof data.detail === "string" ? data.detail : "Something went wrong. Please try again.";
    if (Array.isArray(data.detail)) {
      for (const d of data.detail as { loc: (string | number)[]; msg: string }[]) {
        const field = String(d.loc[d.loc.length - 1]);
        fields[field] = d.msg.replace(/^Value error, /, "");
      }
      message = Object.values(fields)[0] ?? message;
    }
    throw new ApiError(message, res.status, fields);
  }
  return data as T;
}

/** Sign-up/log-in responses carry the session token in token mode; keep it. */
async function withToken(p: Promise<User & { session_token?: string | null }>): Promise<User> {
  const u = await p;
  if (u.session_token) setToken(u.session_token);
  return u;
}

export const signup = (name: string, email: string, password: string) =>
  withToken(call("POST", "/api/auth/signup", { name, email, password }));
export const login = (email: string, password: string) => withToken(call("POST", "/api/auth/login", { email, password }));
export async function logout(): Promise<void> {
  try {
    await call<void>("POST", "/api/auth/logout");
  } finally {
    setToken(null);
  }
}

/** The signed-in user, or null when signed out. */
export async function me(): Promise<User | null> {
  try {
    return await call<User>("GET", "/api/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      setToken(null); // expired or revoked
      return null;
    }
    throw e;
  }
}

export const updateProfile = (p: ProfileInput) => call<User>("PUT", "/api/profile", p);
export async function changePassword(current_password: string, new_password: string): Promise<void> {
  // Other sessions are revoked; in token mode the server hands this page its new token.
  const r = await call<{ session_token?: string } | undefined>("POST", "/api/profile/password", { current_password, new_password });
  if (r?.session_token) setToken(r.session_token);
}
/** Password for normal accounts; Google-only accounts confirm by typing DELETE. */
export async function deleteAccount(password: string, confirm = ""): Promise<void> {
  await call<void>("POST", "/api/profile/delete", { password, confirm });
  setToken(null);
}

/** Which sign-in options the server has set up. */
export async function providers(): Promise<{ google: boolean }> {
  try {
    return await call<{ google: boolean }>("GET", "/api/auth/providers");
  } catch {
    return { google: false };
  }
}

/** Full-page redirect target that starts "Sign in with Google" and comes back to `next`. */
export function googleStartUrl(next: string | null): string {
  const q = new URLSearchParams();
  if (next) q.set("next", safeNext(next));
  if (TOKEN_MODE) q.set("mode", "token"); // come back with the token in the URL fragment
  const qs = q.toString();
  return `${API_URL}/api/auth/google/start${qs ? `?${qs}` : ""}`;
}

/** Messages for ?error= codes the Google callback sends back to the login page. */
export const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  google_state: "That Google sign-in expired or was started in another tab. Please try again.",
  google_failed: "Google sign-in didn't work. Please try again.",
  google_unverified: "Your Google account's email isn't verified, so we can't use it to sign you in.",
  google_not_configured: "Google sign-in isn't set up on this server yet.",
};

export const listTrips = () => call<TripSummary[]>("GET", "/api/trips");
export const getTrip = (id: string) => call<{ id: string; session_id: string; itinerary: Itinerary }>("GET", `/api/trips/${encodeURIComponent(id)}`);
export const deleteTrip = (id: string) => call<void>("DELETE", `/api/trips/${encodeURIComponent(id)}`);

/** Only same-site paths are allowed as post-login redirects (no open redirects). */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}

export const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

/** Save a trip that was planned while signed out (the server takes the itinerary from its own session). */
export const saveSession = (session_id: string) => call<{ trip_id: string }>("POST", "/api/trips/save", { session_id });

/** Download everything stored about the signed-in customer as a JSON file. */
export async function downloadMyData(): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/profile/export`, { credentials: "include", headers: authHeaders() });
  } catch {
    throw new ApiError("Can't reach the server.", 0);
  }
  if (!res.ok) throw new ApiError(res.status === 401 ? "Please log in again." : "Couldn't prepare your data.", res.status);
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "wayfinder-my-data.json";
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

/** Public facts for the Privacy Policy page. */
export async function siteInfo(): Promise<{ privacy_contact: string; visit_retention_days: number }> {
  try {
    return await call("GET", "/api/site-info");
  } catch {
    return { privacy_contact: "", visit_retention_days: 365 };
  }
}
