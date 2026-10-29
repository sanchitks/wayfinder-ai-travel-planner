import type { AgentName, PlaceCategory, Persona } from "./types";

// Localized for India: rupees with Indian digit grouping (₹12,50,000) and en-IN dates.
export const LOCALE = "en-IN";

export function money(v: number, currency = "INR", digits = 0): string {
  try {
    return new Intl.NumberFormat(LOCALE, { style: "currency", currency, maximumFractionDigits: digits }).format(v);
  } catch {
    return `${Math.round(v).toLocaleString(LOCALE)} ${currency}`;
  }
}

/** Compact rupee amounts for tight spaces: ₹45K, ₹1.5L, ₹2.3Cr. */
export function moneyShort(v: number): string {
  if (v >= 1e7) return `₹${+(v / 1e7).toFixed(1)}Cr`;
  if (v >= 1e5) return `₹${+(v / 1e5).toFixed(1)}L`;
  if (v >= 1e3) return `₹${+(v / 1e3).toFixed(0)}K`;
  return `₹${Math.round(v)}`;
}

export function duration(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

export function time(iso: string): string {
  return iso.slice(11, 16);
}

export function shortDate(iso: string, opts: Intl.DateTimeFormatOptions = { weekday: "short", day: "numeric", month: "short" }) {
  // Treat bare YYYY-MM-DD as a local date (not UTC midnight).
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00`) : new Date(iso);
  return d.toLocaleDateString(LOCALE, opts);
}

export function nightsBetween(a: string, b: string): number {
  return Math.round((new Date(`${b}T12:00:00`).getTime() - new Date(`${a}T12:00:00`).getTime()) / 86400000);
}

export function isoDate(d: Date): string {
  const p = (n: number) => n.toString().padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export const AGENTS: { key: AgentName; label: string; role: string }[] = [
  { key: "orchestrator", label: "Orchestrator", role: "Understands you, delegates, compiles" },
  { key: "logistics", label: "Logistics", role: "Live flight fares and Indian Railways trains" },
  { key: "accommodation", label: "Accommodation", role: "Real hotels with live prices from Agoda, Booking.com & more" },
  { key: "experience", label: "Experience", role: "Real sights and restaurants, routed day by day" },
];

export const PERSONAS: { key: Persona; label: string; blurb: string; budget: number }[] = [
  { key: "budget", label: "Budget Backpacker", blurb: "Hostels & homestays, sleeper trains, budget airlines, street food.", budget: 30000 },
  { key: "luxury", label: "Luxury Traveler", blurb: "Heritage palaces, 5-star resorts, business class, fine dining.", budget: 400000 },
  { key: "business", label: "Corporate / Business", blurb: "Fastest flight or Vande Bharat, near the venue, good Wi-Fi.", budget: 100000 },
  { key: "family", label: "Family", blurb: "Family-friendly resorts, AC trains, kid-approved fun, pure-veg options.", budget: 150000 },
];

export const INTERESTS = [
  "Food", "Heritage", "Temples", "Beaches", "Mountains", "Wildlife", "Yoga", "Bazaars", "Museums", "Nightlife",
  "Adventure", "Art",
];

export const DIETS = ["Vegetarian", "Pure veg", "Jain", "Vegan", "Non veg"];

export const POPULAR_DESTINATIONS = [
  "Goa", "Jaipur", "Udaipur", "Kerala", "Manali", "Rishikesh", "Leh", "Varanasi", "Andaman", "Dubai", "Bangkok", "Singapore",
];

export const CATEGORY_LABEL: Record<PlaceCategory, string> = {
  sight: "Landmark", food: "Dining", activity: "Experience", nightlife: "Nightlife", nature: "Outdoors",
  kids: "Family", culture: "Culture", shopping: "Shopping", wellness: "Wellness",
};

export const TRAIN_CLASS: Record<string, string> = {
  SL: "Sleeper (SL)", "3A": "AC 3-Tier (3A)", "2A": "AC 2-Tier (2A)", "1A": "AC First Class (1A)",
  CC: "AC Chair Car (CC)", EC: "Executive Chair Car (EC)",
};

export const DAY_COLORS = ["#c2185b", "#2e7d32", "#1565c0", "#e65100", "#6a1b9a", "#00838f", "#ad1457", "#5d4037"];

export const priceLevel = (n: number) => (n === 0 ? "Free" : "₹".repeat(n));
