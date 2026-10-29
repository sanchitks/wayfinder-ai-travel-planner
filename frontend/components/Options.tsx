"use client";

import { TRAIN_CLASS, duration, money, shortDate, time } from "@/lib/format";
import type { BookingOption, FlightLeg, FlightOption, HotelOption } from "@/lib/types";
import { Icon } from "./Icon";

function Leg({ leg, label, train }: { leg: FlightLeg; label: string; train?: boolean }) {
  const first = leg.segments[0];
  const last = leg.segments[leg.segments.length - 1];
  const total = new Date(last.arrive).getTime() - new Date(first.depart).getTime();
  const stops = leg.segments.slice(0, -1).map((s, i) => {
    const at = new Date(s.arrive).getTime() - new Date(first.depart).getTime();
    return { code: s.destination, pct: total > 0 ? (at / total) * 100 : 50, key: i };
  });
  const dayDiff = Math.round(
    (new Date(last.arrive.slice(0, 10)).getTime() - new Date(first.depart.slice(0, 10)).getTime()) / 86400000,
  );
  return (
    <div>
      <div className="tiny muted" style={{ fontWeight: 600, marginBottom: 6 }}>
        {label} · {shortDate(first.depart)} ·{" "}
        {train ? `${first.flight_number} ${first.carrier}` : Array.from(new Set(leg.segments.map((s) => s.carrier))).join(", ")}
      </div>
      <div className="leg">
        <div>
          <div className="t">{time(first.depart)}</div>
          <div className="code">{first.origin}</div>
        </div>
        <div className="leg-mid">
          <span>{duration(leg.duration_min)}</span>
          <div className="leg-line">
            {stops.map((s) => <span key={s.key} className="stop" style={{ left: `${s.pct}%` }} title={s.code} />)}
          </div>
          <span>
            {leg.stops === 0 ? (train ? "Direct train" : "Nonstop") : `${leg.stops} stop${leg.stops > 1 ? "s" : ""} · ${stops.map((s) => s.code).join(", ")}`}
            {leg.stops > 0 && ` · longest layover ${duration(leg.max_layover_min)}`}
          </span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="t">{time(last.arrive)}{dayDiff > 0 && <sup className="tiny" style={{ color: "var(--sun)" }}> +{dayDiff}</sup>}</div>
          <div className="code">{last.destination}</div>
        </div>
      </div>
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  demo: "Sample data",
  openstreetmap: "Real · OpenStreetMap",
  "booking.com": "Live · Booking.com",
  tripadvisor: "Real hotel · TripAdvisor",
  ignav: "Live fare · Ignav",
};

function SourceTag({ source }: { source: string }) {
  return (
    <span className={`tag ${source === "demo" ? "" : "tag-leaf"}`} title="Data source">
      {SOURCE_LABEL[source] ?? source}
    </span>
  );
}

export function FlightCard({ f, selected, compact, onChoose, disabled }: {
  f: FlightOption; selected?: boolean; compact?: boolean; onChoose?: () => void; disabled?: boolean;
}) {
  const isTrain = f.mode === "train";
  if (compact) {
    return (
      <div className="card alt">
        <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
          <Leg leg={f.outbound} label="Outbound" train={isTrain} />
          {f.inbound && <Leg leg={f.inbound} label="Return" train={isTrain} />}
        </div>
        <div className="alt-side">
          <div className="price" style={{ fontSize: 20 }}>{money(f.price, f.currency)}</div>
          <div className="row wrap alt-tags">
            {f.source === "ignav" && <span className="tag tag-leaf" title="Live fare from Ignav">Live fare</span>}
            <span className="tag tag-accent">
              <Icon name={isTrain ? "train" : "plane"} size={12} /> {isTrain ? TRAIN_CLASS[f.cabin] ?? f.cabin : "Flight"}
            </span>
            {f.tags.filter((t) => t !== "Train").slice(0, 2).map((t) => <span key={t} className="tag">{t}</span>)}
          </div>
          {onChoose && <button className="btn btn-sm" onClick={onChoose} disabled={disabled}>Choose</button>}
        </div>
      </div>
    );
  }
  return (
    <article className={`card option ${selected ? "selected" : ""}`}>
      <div className="option-head">
        <div className="row wrap">
          {selected && <span className="tag tag-accent"><Icon name="check" size={12} /> Selected</span>}
          <span className="tag"><Icon name={isTrain ? "train" : "plane"} size={12} /> {isTrain ? "Indian Railways" : "Flight"}</span>
          <span className="tag">{isTrain ? TRAIN_CLASS[f.cabin] ?? f.cabin : f.cabin.replace("_", " ").toLowerCase()}</span>
          {f.tags.filter((t) => t !== "Train").map((t) => <span key={t} className="tag tag-sun">{t}</span>)}
          <SourceTag source={f.source} />
        </div>
        <div className="option-price">
          <div className="price">{money(f.price, f.currency)}</div>
          <div className="tiny muted">round trip, all travellers</div>
          {f.source === "ignav" && (
            <div className="tiny" style={{ color: f.price_verified ? "var(--leaf)" : "var(--sun)" }}>
              {f.price_verified ? "✓ live fare, verified" : "live fare, not yet verified"}
              {f.observed_at && ` · checked ${new Date(f.observed_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`}
            </div>
          )}
        </div>
      </div>
      <Leg leg={f.outbound} label="Outbound" train={isTrain} />
      {f.inbound && <Leg leg={f.inbound} label="Return" train={isTrain} />}
      {f.rationale && (
        <div className="why" style={{ ["--agent" as string]: "var(--a-logistics)" }}>
          <Icon name={isTrain ? "train" : "plane"} size={15} style={{ color: "var(--a-logistics)" }} />
          <span><b>Logistics agent:</b> {f.rationale}</span>
        </div>
      )}
      {f.booking_options.length > 0 ? (
        <BookingOptions options={f.booking_options} />
      ) : (
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <a className="btn btn-primary btn-sm" href={f.booking_url} target="_blank" rel="noreferrer">
            {isTrain ? "Check seats & book on IRCTC" : "Check fares & book"} <Icon name="external" size={14} />
          </a>
        </div>
      )}
    </article>
  );
}

const LEG_LABEL: Record<string, string> = { outbound: "Outbound flight", inbound: "Return flight", "round trip": "Whole trip" };
const SELLER_TYPE: Record<string, string> = { airline: "Airline direct", hotel: "Hotel direct", third_party: "Booking site" };

function BookingOptions({ options, perNight, reviewsUrl }: { options: BookingOption[]; perNight?: boolean; reviewsUrl?: string }) {
  const legs = Array.from(new Set(options.map((o) => o.leg)));
  return (
    <section className="booking-options" aria-label="Where to book">
      <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div className="label">{perNight ? "Live prices per night" : "Where to book"}</div>
        <div className="tiny muted">
          You book and pay on the seller&apos;s site · {perNight ? "prices" : "fares"} can change until you pay
        </div>
      </div>
      {legs.map((leg) => (
        <div key={leg} className="booking-leg">
          {legs.length > 1 && <div className="tiny muted" style={{ fontWeight: 600 }}>{LEG_LABEL[leg] ?? leg} (booked separately)</div>}
          {options.filter((o) => o.leg === leg).slice(0, 4).map((o, i) => (
            <div key={`${o.provider}-${i}`} className="booking-row">
              <div className="booking-seller row wrap" style={{ gap: 6 }}>
                <b>{o.provider}</b>
                <span className={`tag ${o.provider_type !== "third_party" ? "tag-accent" : ""}`}>
                  {SELLER_TYPE[o.provider_type ?? "third_party"] ?? "Booking site"}
                </span>
                {o.exact_flight && <span className="tag">This exact flight</span>}
                {perNight && i === 0 && options.filter((x) => x.leg === leg).length > 1 && <span className="tag tag-leaf">Lowest</span>}
              </div>
              {o.price !== null && (
                <span className="booking-price" title={o.price_verified ? "Live price" : "Unverified price"}>
                  {money(o.price, o.currency)}{perNight && <span className="tiny muted"> /night</span>}
                  {!o.price_verified && <span className="tiny muted"> (unverified)</span>}
                </span>
              )}
              <a className={`btn btn-sm ${i === 0 ? "btn-primary" : ""}`} href={o.url} target="_blank" rel="noreferrer"
                title={reviewsUrl && o.url === reviewsUrl ? "Opens TripAdvisor's deal list for this hotel" : undefined}>
                {reviewsUrl && o.url === reviewsUrl ? "View deal" : "Book"} <Icon name="external" size={13} />
              </a>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

export function Stars({ n, estimated }: { n: number; estimated?: boolean }) {
  const full = Math.floor(n);
  return (
    <span
      className="stars"
      aria-label={`${estimated ? "about " : ""}${n} stars`}
      title={estimated ? "Estimated star class (not officially rated)" : undefined}
      style={estimated ? { opacity: 0.75 } : undefined}
    >
      {estimated && <span className="tiny" style={{ marginRight: 2 }}>~</span>}
      {Array.from({ length: full }, (_, i) => <Icon key={i} name="star" size={13} fill="currentColor" strokeWidth={0} />)}
      {n - full >= 0.5 && <span className="tiny" style={{ color: "#e0a100" }}>½</span>}
      {estimated && <span className="tiny muted" style={{ marginLeft: 4 }}>est.</span>}
    </span>
  );
}

function Price({ h, size }: { h: HotelOption; size?: "lg" }) {
  const est = h.estimated.includes("price");
  const live = !est && h.booking_options.length > 0;
  return (
    <span title={est ? "Estimated from the property type and local price levels - check live rates"
      : live ? `Lowest live price from ${h.booking_options[0].provider}` : undefined}>
      <span className={size === "lg" ? "price" : undefined} style={size ? undefined : { fontWeight: 700 }}>
        {est && "≈ "}{money(h.price_per_night, h.currency)}
      </span>
      {!size && <span className="small muted"> / night{est ? " est." : live ? " live" : ""}</span>}
    </span>
  );
}

function Rating({ h, compact }: { h: HotelOption; compact?: boolean }) {
  if (h.rating === null) return null;
  const ta = h.source === "tripadvisor";
  const label = `${h.rating.toFixed(1)}${h.rating_scale === 5 ? "/5" : ""}`;
  if (compact) return <div className="rating" title={ta ? "TripAdvisor rating" : undefined}><b>{label}</b></div>;
  return (
    <span className="rating">
      <b>{label}</b>
      {h.reviews_url ? (
        <a href={h.reviews_url} target="_blank" rel="noreferrer">{h.review_count.toLocaleString("en-IN")} {ta ? "TripAdvisor " : ""}reviews</a>
      ) : (
        <>{h.review_count.toLocaleString("en-IN")} reviews</>
      )}
    </span>
  );
}

function Contact({ h }: { h: HotelOption }) {
  const website = h.website && (h.website.startsWith("http") ? h.website : `https://${h.website}`);
  if (!h.phone && !website && !h.maps_url) return null;
  return (
    <div className="row wrap small" style={{ gap: 14 }}>
      {h.phone && (
        <a href={`tel:${h.phone.split(";")[0].replace(/\s+/g, "")}`} className="row" style={{ gap: 5 }}>
          <Icon name="phone" size={14} /> {h.phone.split(";")[0]}
        </a>
      )}
      {website && (
        <a href={website} target="_blank" rel="noreferrer" className="row" style={{ gap: 5 }}>
          <Icon name="globe" size={14} /> Website
        </a>
      )}
      {h.maps_url && (
        <a href={h.maps_url} target="_blank" rel="noreferrer" className="row" style={{ gap: 5 }}>
          <Icon name="map" size={14} /> View on map
        </a>
      )}
    </div>
  );
}

function photoStyle(h: HotelOption) {
  if (h.photo_url) return { backgroundImage: `url(${h.photo_url})` };
  let hash = 0;
  for (const ch of h.name) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return { background: `linear-gradient(135deg, hsl(${hash} 45% 42%), hsl(${(hash + 50) % 360} 55% 30%))` };
}

export function HotelCard({ h, nights, selected, onChoose, disabled }: {
  h: HotelOption; nights: number; selected?: boolean; onChoose?: () => void; disabled?: boolean;
}) {
  const real = h.source !== "demo";
  const starsEst = h.estimated.includes("stars");
  if (!selected) {
    return (
      <article className="card option" style={{ padding: 0, overflow: "hidden", gap: 0 }}>
        <div className={`hotel-photo ${h.photo_url ? "" : "placeholder"}`} style={{ ...photoStyle(h), minHeight: 96, borderRadius: 0 }}>
          {!h.photo_url && <Icon name="bed" size={28} />}
          <span className="tag photo-badge">{real ? "Real hotel" : "Sample"}</span>
          <span className="photo-plate">{h.kind}</span>
        </div>
        <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 7 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div className="grow">
              <div style={{ fontWeight: 650 }}>{h.name}</div>
              <div className="row wrap small muted" style={{ gap: 6 }}>
                <Stars n={h.stars} estimated={starsEst} /> · <span style={{ textTransform: "capitalize" }}>{h.kind}</span> · {h.distance_km.toFixed(1)} km
              </div>
            </div>
            <Rating h={h} compact />
          </div>
          {real && h.address && <div className="tiny muted one-line" title={h.address}><Icon name="pin" size={11} /> {h.address}</div>}
          <div className="row" style={{ justifyContent: "space-between" }}>
            <Price h={h} />
            {onChoose && <button className="btn btn-sm" onClick={onChoose} disabled={disabled}>Choose</button>}
          </div>
          <div className="row wrap">{h.tags.slice(0, 3).map((t) => <span key={t} className="tag">{t}</span>)}</div>
        </div>
      </article>
    );
  }
  return (
    <article className="card option selected">
      <div className="hotel-hero">
        <div className={`hotel-photo ${h.photo_url ? "" : "placeholder"}`} style={photoStyle(h)}>
          {!h.photo_url && <Icon name="bed" size={36} />}
          <span className="photo-plate">{h.kind}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 0 }}>
          <div className="option-head">
            <div className="grow">
              <div className="row wrap" style={{ marginBottom: 6 }}>
                <span className="tag tag-accent"><Icon name="check" size={12} /> Selected</span>
                {h.tags.map((t) => <span key={t} className="tag tag-sun">{t}</span>)}
                <SourceTag source={h.source} />
              </div>
              <h3 className="display" style={{ fontSize: 22 }}>{h.name}</h3>
              <div className="row wrap small muted" style={{ marginTop: 4 }}>
                <Stars n={h.stars} estimated={starsEst} />
                {h.rating !== null ? (
                  <Rating h={h} />
                ) : (
                  real && <span className="tiny">No guest rating yet - see reviews on Booking.com</span>
                )}
                <span className="row" style={{ gap: 4 }}><Icon name="route" size={13} /> {h.distance_km.toFixed(1)} km away</span>
              </div>
              {real && h.address && (
                <div className="row small" style={{ gap: 5, marginTop: 6, color: "var(--ink-2)" }}>
                  <Icon name="pin" size={13} /> {h.address}
                </div>
              )}
            </div>
            <div className="option-price">
              <Price h={h} size="lg" />
              <div className="tiny muted">
                per night · {h.estimated.includes("price") ? "≈ " : ""}{money(h.total_price, h.currency)} for {nights} nights
              </div>
              {h.estimated.includes("price") && <div className="tiny" style={{ color: "var(--sun)" }}>estimated</div>}
              {h.price_checked_at && (
                <div className="tiny" style={{ color: "var(--leaf)" }}>
                  ✓ live price · checked {new Date(h.price_checked_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                </div>
              )}
            </div>
          </div>
          {h.amenities.length > 0 && (
            <div className="amenities">{h.amenities.slice(0, 12).map((a) => <span key={a} className="tag">{a}</span>)}</div>
          )}
          <Contact h={h} />
          {h.rationale && (
            <div className="why">
              <Icon name="bed" size={15} style={{ color: "var(--a-accommodation)" }} />
              <span><b>Accommodation agent:</b> {h.rationale}</span>
            </div>
          )}
          {h.source === "openstreetmap" && (
            <div className="tiny muted">
              Real property listed on OpenStreetMap. The nightly price{starsEst ? " and star class are" : " is an"} estimate
              {starsEst ? "s" : ""} - check live rates and reviews before booking.
            </div>
          )}
          {h.booking_options.length > 0 ? (
            <BookingOptions options={h.booking_options} perNight reviewsUrl={h.reviews_url} />
          ) : (
            <div className="row" style={{ justifyContent: "flex-end", marginTop: "auto" }}>
              <a className="btn btn-primary btn-sm" href={h.booking_url} target="_blank" rel="noreferrer">
                {h.estimated.includes("price") ? "Check live rates on Booking.com" : "View & book"} <Icon name="external" size={14} />
              </a>
            </div>
          )}
          {h.source === "tripadvisor" && (
            <div className="tiny muted">Hotel details and ratings from TripAdvisor; live prices via Xotelo.</div>
          )}
        </div>
      </div>
    </article>
  );
}
