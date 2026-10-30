// How this copy of the website is deployed. Locally everything is on localhost and the login
// rides in an HttpOnly cookie. On GitHub Pages the site lives under /<repo>/ and the API is on
// another site (Render), where browsers block cross-site cookies, so the login is a token kept
// in localStorage and sent in the Authorization header ("token mode").

/** "/wayfinder-ai-travel-planner" on GitHub Pages, "" locally. */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
export const TOKEN_MODE = process.env.NEXT_PUBLIC_AUTH_MODE === "token";
const TRAILING_SLASH = process.env.NEXT_PUBLIC_TRAILING_SLASH === "1";

/** A file in /public, e.g. asset("/photos/goa.jpg"). (next/link adds the base path itself; plain URLs don't.) */
export const asset = (path: string) => `${BASE_PATH}${path}`;

/** A page address for history.replaceState, e.g. pageUrl("/profile", "?tab=trips"). */
export function pageUrl(path: string, query = "") {
  const p = TRAILING_SLASH && !path.endsWith("/") ? `${path}/` : path;
  return `${BASE_PATH}${p}${query}`;
}

const TOKEN_KEY = "wf-token";
const VISITOR_KEY = "wf-visitor";

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // private mode / blocked storage
  }
}

export function getToken(): string | null {
  return TOKEN_MODE ? store()?.getItem(TOKEN_KEY) ?? null : null;
}

export function setToken(token: string | null | undefined) {
  if (!TOKEN_MODE) return;
  try {
    if (token) store()?.setItem(TOKEN_KEY, token);
    else store()?.removeItem(TOKEN_KEY);
  } catch {}
}

/** Headers that carry the login: the token in token mode, nothing when the cookie does the job. */
export function authHeaders(): Record<string, string> {
  if (!TOKEN_MODE) return {};
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}`, "X-Auth-Mode": "token" } : { "X-Auth-Mode": "token" };
}

/** In token mode the page keeps its own random visitor ID (the cookie can't cross sites). */
export function visitorHeaders(): Record<string, string> {
  if (!TOKEN_MODE) return {};
  const s = store();
  let id = s?.getItem(VISITOR_KEY) ?? "";
  if (!/^[0-9a-f]{32}$/.test(id)) {
    id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
    try {
      s?.setItem(VISITOR_KEY, id);
    } catch {}
  }
  return { "X-Visitor-Id": id };
}

/** Google sign-in returns with #wf_token=...: store it and remove it from the address bar. */
export function takeTokenFromUrl() {
  if (!TOKEN_MODE || typeof window === "undefined") return;
  const m = /(?:^|[#&])wf_token=([^&]+)/.exec(window.location.hash);
  if (!m) return;
  setToken(decodeURIComponent(m[1]));
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}
