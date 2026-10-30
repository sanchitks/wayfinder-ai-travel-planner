"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import ChatPanel from "@/components/ChatPanel";
import { Icon } from "@/components/Icon";
import ItineraryPanel from "@/components/ItineraryPanel";
import Onboarding, { applyProfile, defaultRequest } from "@/components/Onboarding";
import ThemeSwitch from "@/components/ThemeSwitch";
import UserMenu from "@/components/UserMenu";
import { SessionExpiredError, getHealth, planTrip, refineTrip, selectOption } from "@/lib/api";
import { ApiError, getTrip, saveSession } from "@/lib/auth";
import { pageUrl } from "@/lib/site";
import { PERSONAS, money, nightsBetween, shortDate } from "@/lib/format";
import type { AgentName, AgentState, ChatMessage, Health, Itinerary, StreamEvent, TripRequest } from "@/lib/types";

const idle = (): Record<AgentName, AgentState> => ({
  orchestrator: { status: "idle", message: "", log: [] },
  logistics: { status: "idle", message: "", log: [] },
  accommodation: { status: "idle", message: "", log: [] },
  experience: { status: "idle", message: "", log: [] },
});

let msgSeq = 0;
const msg = (role: ChatMessage["role"], content: string): ChatMessage => ({ id: `m${++msgSeq}`, role, content });

function briefText(r: TripRequest): string {
  const persona = PERSONAS.find((p) => p.key === r.persona)!.label;
  const nights = nightsBetween(r.start_date, r.end_date);
  const who = `${r.adults} adult${r.adults > 1 ? "s" : ""}${r.children ? ` + ${r.children} kid${r.children > 1 ? "s" : ""}` : ""}`;
  return [
    `${r.origin} → ${r.destination}, ${shortDate(r.start_date)}–${shortDate(r.end_date)} (${nights} nights)`,
    `${who} · ${persona} · ${money(r.budget)} budget`,
    r.interests.length ? `Into: ${r.interests.join(", ")}` : "",
    r.notes,
  ].filter(Boolean).join("\n");
}

export default function Home() {
  const [phase, setPhase] = useState<"onboarding" | "workspace">("onboarding");
  const [form, setForm] = useState<TripRequest>(defaultRequest);
  const [request, setRequest] = useState<TripRequest | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [agents, setAgents] = useState(idle);
  const [itinerary, setItinerary] = useState<Itinerary | null>(null);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const [view, setView] = useState<"chat" | "plan">("chat");
  const abortRef = useRef<AbortController | null>(null);
  const { user, loading: authLoading, refresh } = useAuth();
  const router = useRouter();
  const [savedTripId, setSavedTripId] = useState<string | null>(null);
  const [formVersion, setFormVersion] = useState(0); // remounts the form when profile defaults arrive
  const prefilledFor = useRef<number | null>(null);
  const linkHandled = useRef(false);

  useEffect(() => {
    getHealth().then(setHealth);
  }, []);

  // Signed in: start new trips from the profile's home city, style, budget and interests.
  useEffect(() => {
    if (!user || prefilledFor.current === user.id || request) return;
    prefilledFor.current = user.id;
    setForm((f) => applyProfile(f, user));
    setFormVersion((v) => v + 1);
  }, [user, request]);

  const openItinerary = useCallback((it: Itinerary, sid: string, tripId: string | null, note: string, history?: ChatMessage[]) => {
    setItinerary(it);
    setRequest(it.request);
    setForm(it.request);
    setSessionId(sid);
    setSavedTripId(tripId);
    setAgents(idle());
    setMessages([...(history ?? []), msg("assistant", note)]);
    setPhase("workspace");
    setView("plan");
  }, []);

  // /?trip=<id> opens a saved trip; /?resume=1 restores the plan made just before logging in.
  useEffect(() => {
    if (authLoading || linkHandled.current) return;
    const q = new URLSearchParams(window.location.search);
    const tripId = q.get("trip");
    const resume = q.get("resume");
    if (!tripId && !resume) return;
    linkHandled.current = true;
    window.history.replaceState(null, "", pageUrl("/"));
    if (tripId) {
      if (!user) {
        router.replace(`/login?next=${encodeURIComponent(`/?trip=${tripId}`)}`);
        return;
      }
      getTrip(tripId)
        .then((t) => openItinerary(t.itinerary, t.session_id, t.id,
          `Here's your saved trip to ${t.itinerary.request.destination}. Ask me for any changes - they're saved automatically.`))
        .catch((err) => {
          setPhase("workspace");
          setMessages([msg("system", err instanceof ApiError ? err.message : "Couldn't open that trip.")]);
        });
      return;
    }
    let pending: { sessionId: string; itinerary: Itinerary; messages: ChatMessage[] } | null = null;
    try {
      pending = JSON.parse(sessionStorage.getItem("wf-pending-trip") ?? "null");
      sessionStorage.removeItem("wf-pending-trip");
    } catch {}
    if (!pending || !user) return;
    openItinerary(pending.itinerary, pending.sessionId, null, "Welcome back! Saving this trip to your account…", pending.messages);
    saveSession(pending.sessionId)
      .then((r) => {
        setSavedTripId(r.trip_id);
        setMessages((m) => [...m, msg("assistant", "Saved. You'll find it under Saved trips in your profile.")]);
        void refresh();
      })
      .catch((err) => setMessages((m) => [...m, msg("system", err instanceof ApiError ? err.message : "Couldn't save this trip.")]));
  }, [authLoading, user, router, openItinerary, refresh]);

  // Signed out: keep the current plan through the login page, then save it there.
  const loginToSave = useCallback(() => {
    if (!sessionId || !itinerary) return;
    try {
      sessionStorage.setItem("wf-pending-trip", JSON.stringify({ sessionId, itinerary, messages }));
    } catch {}
    router.push(`/login?next=${encodeURIComponent("/?resume=1")}`);
  }, [sessionId, itinerary, messages, router]);

  const handleEvent = useCallback((e: StreamEvent) => {
    switch (e.type) {
      case "session":
        setSessionId(e.session_id);
        break;
      case "agent":
        setAgents((prev) => ({
          ...prev,
          [e.agent]: { status: e.status, message: e.message, log: [...prev[e.agent].log, e.message].slice(-8) },
        }));
        break;
      case "message":
        setMessages((m) => [...m, msg("assistant", e.content)]);
        break;
      case "itinerary":
        setItinerary(e.data);
        setRequest(e.data.request);
        setView("plan");
        break;
      case "saved":
        setSavedTripId(e.trip_id);
        void refresh(); // trip count in the user menu
        break;
      case "error":
        setMessages((m) => [...m, msg("system", `Something went wrong: ${e.message}`)]);
        break;
    }
  }, [refresh]);

  const run = useCallback(async (task: (signal: AbortSignal) => Promise<void>) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setBusy(true);
    try {
      await task(ctrl.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") throw err;
    } finally {
      if (abortRef.current === ctrl) setBusy(false);
    }
  }, []);

  const startPlan = useCallback(
    async (req: TripRequest, note = "") => {
      setForm(req);
      setRequest(req);
      setPhase("workspace");
      setView("chat");
      setItinerary(null);
      setSessionId(null);
      setSavedTripId(null);
      setAgents(idle());
      setMessages((m) => (note ? [...m] : [msg("user", briefText(req))]));
      try {
        await run((signal) => planTrip(req, note, handleEvent, signal));
      } catch (err) {
        setMessages((m) => [...m, msg("system", `Couldn't reach the planner: ${(err as Error).message}`)]);
      }
    },
    [handleEvent, run],
  );

  const refine = useCallback(
    async (text: string) => {
      setMessages((m) => [...m, msg("user", text)]);
      setAgents((prev) => {
        const next = idle();
        for (const k of Object.keys(prev) as AgentName[]) next[k] = { ...prev[k], status: "idle", message: prev[k].status === "done" ? "Standing by" : prev[k].message };
        return next;
      });
      if (!request) return;
      if (!sessionId) return startPlan(request, text); // first plan never finished - start over with this note
      try {
        await run((signal) => refineTrip(sessionId, text, handleEvent, signal));
      } catch (err) {
        if (err instanceof SessionExpiredError) {
          setMessages((m) => [...m, msg("system", "The planner restarted and lost this session - re-planning with your latest request.")]);
          await startPlan(request, text);
        } else {
          setMessages((m) => [...m, msg("system", `Couldn't apply that change: ${(err as Error).message}`)]);
        }
      }
    },
    [sessionId, request, handleEvent, run, startPlan],
  );

  const select = useCallback(
    async (kind: "flight" | "hotel", id: string) => {
      if (!sessionId) return;
      setView("plan");
      try {
        await run((signal) => selectOption(sessionId, kind, id, handleEvent, signal));
      } catch (err) {
        setMessages((m) => [...m, msg("system", `Couldn't switch: ${(err as Error).message}`)]);
      }
    },
    [sessionId, handleEvent, run],
  );

  if (phase === "onboarding") {
    return (
      <Onboarding key={formVersion} initial={form} initialDiets={request ? [] : user?.diets ?? []}
        budgetLocked={!!user?.budget} health={health} onSubmit={(r) => startPlan(r)} />
    );
  }

  return (
    <div className="workspace" data-view={view}>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" style={{ width: 30, height: 30 }}><Icon name="compass" size={17} /></div>
          <span className="hide-mobile">Wayfinder</span>
        </div>
        <div className="small muted hide-mobile grow" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {request && `${request.destination} · ${shortDate(request.start_date)}–${shortDate(request.end_date)}`}
        </div>
        <div className="mobile-switch row" role="tablist" aria-label="Switch view">
          <button className={`chip`} aria-pressed={view === "chat"} onClick={() => setView("chat")}>Chat</button>
          <button className={`chip`} aria-pressed={view === "plan"} onClick={() => setView("plan")}>Itinerary</button>
        </div>
        <ThemeSwitch className="topbar-theme" />
        <UserMenu compact />
        <button
          className="btn btn-sm btn-ghost"
          onClick={() => {
            abortRef.current?.abort();
            setBusy(false);
            setPhase("onboarding");
          }}
        >
          <Icon name="edit" size={14} /> <span className="hide-mobile">Edit trip</span>
        </button>
      </header>
      <ChatPanel messages={messages} agents={agents} busy={busy} persona={request?.persona ?? "budget"} onSend={refine} />
      <ItineraryPanel itinerary={itinerary} agents={agents} busy={busy} request={request} onSelect={select}
        account={{ signedIn: !!user, saved: !!savedTripId, onLoginToSave: loginToSave }} />
    </div>
  );
}
