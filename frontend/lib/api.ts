import { authHeaders } from "./site";
import type { GeoPoint, Health, RoadRoute, StreamEvent, TravelProfile, TripRequest } from "./types";

// Default: the backend on port 8000 of whatever host served this page, so the login cookie stays
// same-site (localhost with localhost, 127.0.0.1 with 127.0.0.1). Override with NEXT_PUBLIC_API_URL.
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8000` : "http://localhost:8000")
).replace(/\/$/, "");

export class SessionExpiredError extends Error {}

/**
 * POST a JSON body and consume the Server-Sent Events response.
 * (EventSource only supports GET, so we parse the stream by hand.)
 */
async function streamPost(path: string, body: unknown, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...authHeaders() },
    body: JSON.stringify(body),
    credentials: "include", // signed-in users' trips are saved to their account
    signal,
  });
  if (res.status === 404) throw new SessionExpiredError("Session expired");
  if (!res.ok || !res.body) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      detail = Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join("; ") : j.detail || detail;
    } catch {}
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)) as StreamEvent);
          } catch {
            /* ignore malformed frame */
          }
        }
      }
    }
  }
}

export const planTrip = (request: TripRequest, message: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
  streamPost("/api/plan", { request, message }, onEvent, signal);

export const refineTrip = (sessionId: string, message: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal) =>
  streamPost("/api/refine", { session_id: sessionId, message }, onEvent, signal);

export const selectOption = (
  sessionId: string, kind: "flight" | "hotel", id: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal,
) => streamPost("/api/select", { session_id: sessionId, kind, id }, onEvent, signal);

export async function getHealth(): Promise<Health | null> {
  try {
    const r = await fetch(`${API_URL}/api/health`, { cache: "no-store" });
    return r.ok ? ((await r.json()) as Health) : null;
  } catch {
    return null;
  }
}

/** Road routes through each list of stops; a null entry means it couldn't be routed. */
export async function getRoutes(
  profile: TravelProfile, routes: Record<string, GeoPoint[]>, signal?: AbortSignal,
): Promise<Record<string, RoadRoute | null>> {
  const r = await fetch(`${API_URL}/api/routes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile, routes }),
    signal,
  });
  if (!r.ok) throw new Error(`routes: ${r.status}`);
  return (await r.json()).routes;
}
