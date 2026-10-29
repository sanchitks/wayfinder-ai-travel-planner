"use client";

import { useEffect, useRef, useState } from "react";
import { AGENTS } from "@/lib/format";
import type { AgentName, AgentState, ChatMessage, Persona } from "@/lib/types";
import { Icon } from "./Icon";
import { AGENT_ICON } from "./Onboarding";

const SUGGESTIONS: Record<Persona, string[]> = {
  budget: ["Go by sleeper train", "Find a cheaper hostel", "More street food", "Add free temples & ghats", "Make it more relaxed"],
  luxury: ["Stay in a heritage palace", "Nonstop flights only", "Add an Ayurvedic spa", "More fine dining", "Fewer activities"],
  business: ["Hotel closer to the venue", "Fastest option", "Take Vande Bharat instead", "Avoid red-eye flights", "Hotel with a gym"],
  family: ["Hotel with a pool", "Prefer AC 3-tier train", "Pure veg restaurants only", "Fewer activities per day", "Find a cheaper hotel"],
};

export function AgentBoard({ agents }: { agents: Record<AgentName, AgentState> }) {
  return (
    <div className="agent-board" aria-live="polite">
      {AGENTS.map((a) => {
        const s = agents[a.key];
        return (
          <div key={a.key} className="agent-card" data-status={s.status} style={{ ["--agent" as string]: `var(--a-${a.key})` }}>
            <div className="head">
              <span className="agent-glyph"><Icon name={AGENT_ICON[a.key]} size={13} /></span>
              <span className="agent-name">{a.label}</span>
              <span className="pip" title={s.status} />
            </div>
            <div className="msg">
              {s.message || (s.status === "idle" ? "Standing by" : "")}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function ChatPanel({
  messages,
  agents,
  busy,
  persona,
  onSend,
}: {
  messages: ChatMessage[];
  agents: Record<AgentName, AgentState>;
  busy: boolean;
  persona: Persona;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  function send(value = text) {
    const v = value.trim();
    if (!v || busy) return;
    onSend(v);
    setText("");
    if (inputRef.current) inputRef.current.style.height = "auto";
  }

  return (
    <section className="chat" aria-label="Chat with the orchestrator">
      <AgentBoard agents={agents} />
      <div className="messages" ref={listRef}>
        {messages.map((m) => (
          <div key={m.id} className={`msg-row ${m.role}`}>
            {m.role === "assistant" && (
              <span className="agent-glyph" style={{ ["--agent" as string]: "var(--a-orchestrator)" }}>
                <Icon name="sparkles" size={13} />
              </span>
            )}
            <div className="msg-bubble">{m.content}</div>
          </div>
        ))}
        {busy && (
          <div className="msg-row assistant">
            <span className="agent-glyph" style={{ ["--agent" as string]: "var(--a-orchestrator)" }}>
              <Icon name="sparkles" size={13} />
            </span>
            <div className="msg-bubble typing" aria-label="Agents are working"><i /><i /><i /></div>
          </div>
        )}
      </div>
      <div className="composer">
        <div className="suggestions" role="list" aria-label="Suggested refinements">
          {SUGGESTIONS[persona].map((s) => (
            <button key={s} type="button" className="chip" role="listitem" disabled={busy} onClick={() => send(s)}>
              {s}
            </button>
          ))}
        </div>
        <div className="composer-box">
          <label htmlFor="composer" className="sr-only">Ask for a change</label>
          <textarea
            id="composer"
            ref={inputRef}
            rows={1}
            value={text}
            placeholder={busy ? "Agents are working…" : "Ask for any change…"}
            onChange={(e) => {
              setText(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(120, e.target.scrollHeight)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button type="button" className="send-btn" onClick={() => send()} disabled={busy || !text.trim()} aria-label="Send">
            <Icon name="send" size={16} />
          </button>
        </div>
      </div>
    </section>
  );
}
