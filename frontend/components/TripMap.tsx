"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { LayerGroup, Layer, Map as LeafletMap, Marker } from "leaflet";
import { getRoutes } from "@/lib/api";
import { CATEGORY_LABEL, DAY_COLORS, money, shortDate } from "@/lib/format";
import type { DayPlan, GeoPoint, HotelOption, Itinerary, RoadRoute, ScheduledActivity, TravelProfile } from "@/lib/types";
import { Icon } from "./Icon";

type Leaflet = typeof import("leaflet");
type Base = "map" | "satellite" | "terrain";

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const dayColor = (day: number) => DAY_COLORS[(day - 1) % DAY_COLORS.length];
const ll = (p: GeoPoint) => `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`;

export function fmtDuration(s: number) {
  const m = Math.max(1, Math.round(s / 60));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

export function fmtDistance(m: number) {
  return m < 950 ? `${Math.max(10, Math.round(m / 10) * 10)} m` : `${(m / 1000).toFixed(m < 20000 ? 1 : 0)} km`;
}

/** Google Maps URLs (https://developers.google.com/maps/documentation/urls) need no API key. */
function googlePlace(name: string, where: string) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${name}, ${where}`)}`;
}

function googleDirections(stops: GeoPoint[], mode: TravelProfile) {
  const [origin, ...rest] = stops;
  const destination = rest.pop() ?? origin;
  const waypoints = rest.slice(0, 9).map(ll).join("|"); // Google allows up to 9
  return (
    `https://www.google.com/maps/dir/?api=1&origin=${ll(origin)}&destination=${ll(destination)}` +
    (waypoints ? `&waypoints=${encodeURIComponent(waypoints)}` : "") +
    `&travelmode=${mode}`
  );
}

/** The order a day is travelled in: hotel -> stops -> back to the hotel. */
function dayPath(d: DayPlan, hotel: HotelOption | null): GeoPoint[] {
  const stops = d.activities.map((a) => a.place.location);
  return hotel && stops.length ? [hotel.location, ...stops, hotel.location] : stops;
}

function makeBases(L: Leaflet): Record<Base, Layer> {
  const osm = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const esri = "https://server.arcgisonline.com/ArcGIS/rest/services";
  const tiles = { maxZoom: 20, maxNativeZoom: 19 };
  return {
    map: L.tileLayer(`${esri}/World_Street_Map/MapServer/tile/{z}/{y}/{x}`, {
      ...tiles, attribution: `Tiles &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin, USGS, ${osm}`,
    }),
    satellite: L.layerGroup([
      L.tileLayer(`${esri}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
        ...tiles, attribution: 'Imagery &copy; <a href="https://www.esri.com">Esri</a>, Maxar, Earthstar Geographics',
      }),
      L.tileLayer(`${esri}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`, { ...tiles, opacity: 0.85 }),
      L.tileLayer(`${esri}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, tiles),
    ]),
    terrain: L.tileLayer(`${esri}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`, {
      ...tiles, attribution: `Tiles &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin, USGS, ${osm}`,
    }),
  };
}

function pinIcon(L: Leaflet, color: string, label: string, kind: "stop" | "meal" | "hotel") {
  const glyph = kind === "hotel"
    ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"><path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"/></svg>`
    : esc(label);
  return L.divIcon({
    className: "",
    html:
      `<div class="gpin ${kind}"><svg width="30" height="42" viewBox="0 0 30 42" aria-hidden="true">` +
      `<path d="M15 1C7.3 1 1 7.2 1 14.9 1 25.3 15 41 15 41s14-15.7 14-26.1C29 7.2 22.7 1 15 1z" fill="${color}" stroke="#fff" stroke-width="2"/>` +
      `</svg><span>${glyph}</span></div>`,
    iconSize: [30, 42],
    iconAnchor: [15, 41],
    popupAnchor: [0, -36],
  });
}

function placePopup(a: ScheduledActivity, day: number, city: string, from: GeoPoint | null, mode: TravelProfile) {
  const p = a.place;
  const kind = a.kind === "meal" ? (a.start < "16:00" ? "Lunch" : "Dinner") : CATEGORY_LABEL[p.category];
  const rating = p.rating != null ? ` · ★ ${p.rating.toFixed(1)}${p.review_count ? ` (${p.review_count.toLocaleString("en-IN")})` : ""}` : "";
  const directions = from ? googleDirections([from, p.location], mode) : `https://www.google.com/maps/dir/?api=1&destination=${ll(p.location)}&travelmode=${mode}`;
  const site = p.url && !p.url.includes("google.com/maps")
    ? `<a href="${esc(p.url)}" target="_blank" rel="noreferrer">${p.source === "wikipedia" ? "Wikipedia" : "Website"}</a>`
    : "";
  return (
    `<div class="gpop">` +
    (p.image_url ? `<img src="${esc(p.image_url)}" alt="" loading="lazy"/>` : "") +
    `<div class="gpop-body"><div class="gpop-title">${esc(p.name)}</div>` +
    `<div class="gpop-meta">Day ${day} · ${a.start}–${a.end} · ${kind}${rating}</div>` +
    (p.description ? `<div class="gpop-desc">${esc(p.description)}</div>` : "") +
    (a.note ? `<div class="gpop-desc"><i>${esc(a.note)}</i></div>` : "") +
    `<div class="gpop-actions"><a class="primary" href="${directions}" target="_blank" rel="noreferrer">Directions</a>` +
    `<a href="${googlePlace(p.name, p.address && p.source !== "wikipedia" ? p.address : city)}" target="_blank" rel="noreferrer">Google Maps</a>${site}</div>` +
    `</div></div>`
  );
}

function hotelPopup(h: HotelOption, city: string) {
  return (
    `<div class="gpop">` +
    (h.photo_url ? `<img src="${esc(h.photo_url)}" alt="" loading="lazy"/>` : "") +
    `<div class="gpop-body"><div class="gpop-title">${esc(h.name)}</div>` +
    `<div class="gpop-meta">Your stay · ${h.estimated.includes("price") ? "≈ " : ""}${money(h.price_per_night, h.currency)}/night</div>` +
    (h.address ? `<div class="gpop-desc">${esc(h.address)}</div>` : "") +
    `<div class="gpop-actions"><a class="primary" href="https://www.google.com/maps/dir/?api=1&destination=${ll(h.location)}" target="_blank" rel="noreferrer">Directions</a>` +
    `<a href="${googlePlace(h.name, h.address || city)}" target="_blank" rel="noreferrer">Google Maps</a></div>` +
    `</div></div>`
  );
}

function Leg({ route, i, mode }: { route: RoadRoute | null | undefined; i: number; mode: TravelProfile }) {
  const leg = route?.legs[i];
  if (!leg) return <li className="gleg" aria-hidden="true" />;
  return (
    <li className="gleg">
      <Icon name={mode === "driving" ? "car" : "walk"} size={13} />
      {fmtDuration(leg.duration_s)} · {fmtDistance(leg.distance_m)}
    </li>
  );
}

export default function TripMap({ itinerary }: { itinerary: Itinerary }) {
  const wrap = useRef<HTMLDivElement>(null);
  const el = useRef<HTMLDivElement>(null);
  const lib = useRef<Leaflet | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const bases = useRef<Record<Base, Layer> | null>(null);
  const overlay = useRef<LayerGroup | null>(null);
  const me = useRef<LayerGroup | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const fitted = useRef("");
  const lastBounds = useRef<[number, number][]>([]);

  const [ready, setReady] = useState(false);
  const [day, setDay] = useState<number | "all">("all");
  const [base, setBase] = useState<Base>("map");
  const [mode, setMode] = useState<TravelProfile>("driving");
  const [routeState, setRouteState] = useState<{ key: string; routes: Record<string, RoadRoute | null> } | null>(null);
  const [full, setFull] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [locMsg, setLocMsg] = useState("");
  const [touch, setTouch] = useState(false);
  const [hint, setHint] = useState(false);

  const hotel = itinerary.hotel;
  const city = itinerary.request.destination;
  const days = itinerary.days.filter((d) => d.activities.length > 0);
  const visible = day === "all" ? days : days.filter((d) => d.day === day);
  const samplePlaces = /demo/.test(itinerary.data_sources.experiences ?? "");

  const paths = useMemo(() => {
    const out: Record<string, GeoPoint[]> = {};
    for (const d of itinerary.days) {
      const p = dayPath(d, itinerary.hotel);
      if (p.length >= 2) out[String(d.day)] = p;
    }
    return out;
  }, [itinerary]);
  const routeKey = `${mode}|${JSON.stringify(paths)}`;
  const routes = routeState?.key === routeKey ? routeState.routes : null;
  const routing = routeState?.key !== routeKey && Object.keys(paths).length > 0;

  // Road routes for every day (one request); the map shows straight lines until they arrive.
  useEffect(() => {
    if (!Object.keys(paths).length) return;
    const ctl = new AbortController();
    getRoutes(mode, paths, ctl.signal)
      .then((r) => setRouteState({ key: routeKey, routes: r }))
      .catch(() => { if (!ctl.signal.aborted) setRouteState({ key: routeKey, routes: {} }); });
    return () => ctl.abort();
    // routeKey captures paths + mode
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  // Create the map once (Leaflet touches `window`, so import it client-side).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const L = (await import("leaflet")).default;
      if (cancelled || !el.current || mapRef.current) return;
      lib.current = L;
      const c = itinerary.destination_center ?? itinerary.hotel?.location ?? { lat: 22.5, lng: 79 };
      const map = L.map(el.current, { zoomControl: false, scrollWheelZoom: true }).setView([c.lat, c.lng], 13);
      L.control.zoom({ position: "bottomright" }).addTo(map);
      L.control.scale({ position: "bottomleft", imperial: false }).addTo(map);
      bases.current = makeBases(L);
      bases.current.map.addTo(map);
      overlay.current = L.layerGroup().addTo(map);
      me.current = L.layerGroup().addTo(map);
      mapRef.current = map;
      setReady(true);
    })();
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !bases.current) return;
    for (const [k, layer] of Object.entries(bases.current)) {
      if (k === base) {
        if (!map.hasLayer(layer)) layer.addTo(map);
      } else map.removeLayer(layer);
    }
  }, [base, ready]);

  // Draw routes and pins whenever the plan, the day filter or the routes change.
  useEffect(() => {
    const L = lib.current, map = mapRef.current, layer = overlay.current;
    if (!ready || !L || !map || !layer) return;
    layer.clearLayers();
    markers.current.clear();
    const bounds: [number, number][] = [];

    for (const d of visible) {
      const path = paths[String(d.day)];
      if (!path) continue;
      const color = dayColor(d.day);
      const r = routes?.[String(d.day)];
      if (r) {
        L.polyline(r.geometry, { color: "#ffffff", weight: 9, opacity: 0.95, interactive: false }).addTo(layer);
        L.polyline(r.geometry, { color, weight: 5, opacity: 0.95 })
          .bindTooltip(`Day ${d.day}: ${fmtDistance(r.distance_m)} · ${fmtDuration(r.duration_s)} ${mode === "driving" ? "by road" : "on foot"}`, { sticky: true })
          .addTo(layer);
      } else {
        L.polyline(path.map((p) => [p.lat, p.lng] as [number, number]), { color, weight: 3, opacity: 0.6, dashArray: "4 8", interactive: false }).addTo(layer);
      }
    }

    if (hotel) {
      const m = L.marker([hotel.location.lat, hotel.location.lng], { icon: pinIcon(L, "#1a1d24", "", "hotel"), zIndexOffset: 1000, title: hotel.name })
        .bindPopup(hotelPopup(hotel, city), { minWidth: 250, maxWidth: 250 })
        .on("click", () => setActive("hotel"))
        .addTo(layer);
      markers.current.set("hotel", m);
      bounds.push([hotel.location.lat, hotel.location.lng]);
    }
    for (const d of visible) {
      d.activities.forEach((a, i) => {
        const key = `${d.day}-${i}`;
        const pos: [number, number] = [a.place.location.lat, a.place.location.lng];
        const m = L.marker(pos, { icon: pinIcon(L, dayColor(d.day), String(i + 1), a.kind === "meal" ? "meal" : "stop"), title: a.place.name })
          .bindPopup(placePopup(a, d.day, city, hotel?.location ?? null, mode), { minWidth: 250, maxWidth: 250 })
          .on("click", () => setActive(key))
          .addTo(layer);
        markers.current.set(key, m);
        bounds.push(pos);
      });
    }

    lastBounds.current = bounds;
    const fitKey = `${itinerary.version}|${itinerary.generated_at}|${day}`;
    if (bounds.length && fitted.current !== fitKey) {
      fitted.current = fitKey;
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 15 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, itinerary, day, routes, mode]);

  // Touch screens: like Google Maps embeds, one finger scrolls the page and two fingers move the
  // map, so the map can't trap the scroll. In full screen one finger pans as usual.
  useEffect(() => {
    const mq = window.matchMedia("(pointer: coarse)");
    const update = () => setTouch(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (touch && !full) map.dragging.disable();
    else map.dragging.enable();
    if (!touch || full || !el.current) return;
    const node = el.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return setHint(false);
      setHint(true);
      clearTimeout(timer);
      timer = setTimeout(() => setHint(false), 1400);
    };
    node.addEventListener("touchmove", onMove, { passive: true });
    return () => { clearTimeout(timer); node.removeEventListener("touchmove", onMove); setHint(false); };
  }, [ready, touch, full]);

  // Fullscreen: the browser API where available, otherwise a fixed overlay.
  useEffect(() => {
    const onChange = () => setFull(document.fullscreenElement === wrap.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);
  useEffect(() => {
    const t = setTimeout(() => mapRef.current?.invalidateSize(), 60);
    if (!full) return () => clearTimeout(t);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !document.fullscreenElement && setFull(false);
    window.addEventListener("keydown", onKey);
    return () => { clearTimeout(t); window.removeEventListener("keydown", onKey); };
  }, [full]);

  const toggleFull = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (full) setFull(false);
    else if (wrap.current?.requestFullscreen) wrap.current.requestFullscreen().catch(() => setFull(true));
    else setFull(true);
  };

  const focus = (key: string) => {
    const m = markers.current.get(key), map = mapRef.current;
    if (!m || !map) return;
    setActive(key);
    el.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    map.flyTo(m.getLatLng(), Math.max(map.getZoom(), 16), { duration: 0.6 });
    m.openPopup();
  };

  const fitAll = () => {
    if (lastBounds.current.length) mapRef.current?.fitBounds(lastBounds.current, { padding: [48, 48], maxZoom: 15 });
  };

  const locate = () => {
    if (!navigator.geolocation) return setLocMsg("Location isn't available in this browser.");
    setLocMsg("Finding you…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const L = lib.current, map = mapRef.current, layer = me.current;
        if (!L || !map || !layer) return;
        const p: [number, number] = [pos.coords.latitude, pos.coords.longitude];
        layer.clearLayers();
        L.circle(p, { radius: pos.coords.accuracy, color: "#1a73e8", weight: 1, fillOpacity: 0.12, interactive: false }).addTo(layer);
        L.circleMarker(p, { radius: 8, color: "#fff", weight: 3, fillColor: "#1a73e8", fillOpacity: 1 }).bindTooltip("You are here").addTo(layer);
        map.flyTo(p, 15);
        setLocMsg("");
      },
      () => setLocMsg("Couldn't get your location. Check the browser's location permission."),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const hotelRow = (label: string) =>
    hotel && (
      <li>
        <button className={`gstop${active === "hotel" ? " active" : ""}`} onClick={() => focus("hotel")}>
          <span className="gstop-pin" style={{ background: "#1a1d24" }}><Icon name="bed" size={12} /></span>
          <span className="grow">
            <span className="gstop-name">{hotel.name}</span>
            <span className="gstop-meta">{label}</span>
          </span>
        </button>
      </li>
    );

  return (
    <div className="gmap-wrap">
      <div ref={wrap} className={`gmap${full ? " is-full" : ""}`}>
        <aside className="gmap-side" aria-label="Route by day">
          <div className="gmap-side-head">
            <div className="seg" role="group" aria-label="Travel mode">
              <button aria-pressed={mode === "driving"} onClick={() => setMode("driving")}><Icon name="car" size={15} /> Drive</button>
              <button aria-pressed={mode === "walking"} onClick={() => setMode("walking")}><Icon name="walk" size={15} /> Walk</button>
            </div>
            <div className="gmap-days" role="toolbar" aria-label="Filter map by day">
              <button className="chip" aria-pressed={day === "all"} onClick={() => setDay("all")}>All days</button>
              {days.map((d) => (
                <button key={d.day} className="chip" aria-pressed={day === d.day} onClick={() => setDay(d.day)}>
                  <i style={{ width: 9, height: 9, borderRadius: 3, background: dayColor(d.day), display: "inline-block" }} />
                  Day {d.day}
                </button>
              ))}
            </div>
          </div>

          <div className="gmap-list">
            {visible.map((d) => {
              const path = paths[String(d.day)];
              const r = routes?.[String(d.day)];
              const off = hotel ? 0 : -1; // leg i ends at stop i when the day starts from the hotel
              return (
                <section key={d.day} className="gday">
                  <header className="gday-head">
                    <span className="day-badge sm" style={{ background: dayColor(d.day) }}>{d.day}</span>
                    <div className="grow">
                      <div className="gday-title">{d.theme || `Day ${d.day}`}</div>
                      <div className="tiny muted">
                        {shortDate(d.date)} ·{" "}
                        {r ? `${fmtDistance(r.distance_m)} · ${fmtDuration(r.duration_s)} ${mode === "driving" ? "by road" : "on foot"}`
                          : routing ? "Finding road route…" : `≈ ${d.travel_km} km between stops`}
                      </div>
                    </div>
                  </header>
                  {path && (
                    <a className="btn btn-sm gday-open" href={googleDirections(path, mode)} target="_blank" rel="noreferrer"
                      title={`Open day ${d.day}'s route in Google Maps`}>
                      <Icon name="external" size={13} /> Open day {d.day} in Google Maps
                    </a>
                  )}
                  <ol className="gstops">
                    {hotelRow("Start from your hotel")}
                    {d.activities.map((a, i) => {
                      const key = `${d.day}-${i}`;
                      return (
                        <Fragment key={key}>
                          {i + off >= 0 && <Leg route={r} i={i + off} mode={mode} />}
                          <li>
                            <button className={`gstop${active === key ? " active" : ""}`} onClick={() => focus(key)}>
                              <span className="gstop-pin" style={{ background: dayColor(d.day) }}>{i + 1}</span>
                              <span className="grow">
                                <span className="gstop-name">{a.place.name}</span>
                                <span className="gstop-meta">
                                  {a.start}–{a.end} · {a.kind === "meal" ? (a.start < "16:00" ? "Lunch" : "Dinner") : CATEGORY_LABEL[a.place.category]}
                                </span>
                              </span>
                            </button>
                          </li>
                        </Fragment>
                      );
                    })}
                    {hotel && <Leg route={r} i={d.activities.length + off} mode={mode} />}
                    {hotelRow("Back to your hotel")}
                  </ol>
                </section>
              );
            })}
          </div>
          <div className="gmap-note tiny muted">
            {samplePlaces ? "Some stops are sample places at approximate locations. " : "Pins are real places from Wikipedia and OpenStreetMap. "}
            Routes from OSRM on OpenStreetMap roads; times exclude live traffic.
          </div>
        </aside>

        <div className="gmap-canvas">
          <div ref={el} className="map" />
          <div className="map-ctl tl map-seg" role="group" aria-label="Map type">
            {(["map", "satellite", "terrain"] as Base[]).map((b) => (
              <button key={b} aria-pressed={base === b} onClick={() => setBase(b)}>{b[0].toUpperCase() + b.slice(1)}</button>
            ))}
          </div>
          <div className="map-ctl tr">
            <button className="map-btn" onClick={toggleFull} title={full ? "Exit full screen" : "Full screen"} aria-label={full ? "Exit full screen" : "Full screen"}>
              <Icon name={full ? "minimize" : "maximize"} size={18} />
            </button>
            <button className="map-btn" onClick={fitAll} title="Show the whole trip" aria-label="Show the whole trip"><Icon name="route" size={18} /></button>
            <button className="map-btn" onClick={locate} title="Show my location" aria-label="Show my location"><Icon name="locate" size={18} /></button>
          </div>
          {locMsg && <div className="map-toast" role="status">{locMsg}</div>}
          <div className={`map-hint${hint ? " show" : ""}`} aria-hidden="true">Use two fingers to move the map</div>
        </div>
      </div>
    </div>
  );
}
