"use client";

import { CATEGORY_LABEL, DAY_COLORS, money, priceLevel, shortDate } from "@/lib/format";
import type { DayPlan, PlaceCategory, ScheduledActivity } from "@/lib/types";
import { Icon, type IconName } from "./Icon";

const CATEGORY_ICON: Record<PlaceCategory, IconName> = {
  sight: "pin", food: "utensils", activity: "sparkles", nightlife: "star", nature: "compass",
  kids: "users", culture: "layers", shopping: "wallet", wellness: "sparkles",
};

function Stop({ a, party }: { a: ScheduledActivity; party: number }) {
  const p = a.place;
  const cost = p.est_cost_per_person * party;
  return (
    <li className={`stop-item ${a.kind}`}>
      <div className="when">{a.start}<span className="muted"> – {a.end}</span></div>
      <div className="rail"><div className="node"><Icon name={CATEGORY_ICON[p.category]} size={14} /></div></div>
      <div className="stop-body">
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="name">{p.name}</span>
          {p.url && (
            <a href={p.url} target="_blank" rel="noreferrer" aria-label={`Open ${p.name}`} className="muted" style={{ display: "inline-flex" }}>
              <Icon name="external" size={13} />
            </a>
          )}
        </div>
        <div className="row wrap tiny muted" style={{ gap: 8 }}>
          <span className="tag">{a.kind === "meal" ? (a.start < "16:00" ? "Lunch" : "Dinner") : CATEGORY_LABEL[p.category]}</span>
          {p.rating != null && <span>★ {p.rating.toFixed(1)}</span>}
          {p.source === "wikipedia" && p.description && <span>{p.description}</span>}
          <span>{priceLevel(p.price_level)}</span>
          {cost > 0 && <span>≈ {money(cost)} for your group</span>}
          {p.tags.includes("kid-friendly") && <span className="tag tag-accent">Kid-friendly</span>}
          {p.tags.includes("accessible") && <span className="tag">Accessible</span>}
          {p.source === "demo" && <span className="tag">Sample</span>}
        </div>
        {a.note && <div className="note">{a.note}</div>}
      </div>
    </li>
  );
}

export default function Days({ days, party }: { days: DayPlan[]; party: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {days.map((d) => (
        <article key={d.day} id={`day-${d.day}`} className="card day">
          <div className="day-head">
            <div className="day-badge" style={{ background: DAY_COLORS[(d.day - 1) % DAY_COLORS.length] }}>{d.day}</div>
            <div className="grow">
              <h3 className="display" style={{ fontSize: 19 }}>{d.theme || `Day ${d.day}`}</h3>
              <div className="small muted">
                {shortDate(d.date, { weekday: "long", month: "short", day: "numeric" })}
                {d.area && ` · ${d.area}`}
                {d.travel_km > 0 && ` · ${d.travel_km} km between stops`}
              </div>
            </div>
          </div>
          {d.activities.length ? (
            <ol className="timeline">{d.activities.map((a, i) => <Stop key={`${a.place.id}-${i}`} a={a} party={party} />)}</ol>
          ) : (
            <div className="empty-day">
              {d.theme === "In transit" ? "You're in the air - rest up." : "Nothing scheduled around your flights. Enjoy the downtime."}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
