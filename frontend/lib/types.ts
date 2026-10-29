// Mirrors backend/app/models.py

export type Persona = "budget" | "luxury" | "business" | "family";
export type AgentName = "orchestrator" | "logistics" | "accommodation" | "experience";
export type AgentStatus = "idle" | "working" | "done" | "error";

export interface TripRequest {
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  adults: number;
  children: number;
  budget: number;
  persona: Persona;
  interests: string[];
  flexible_dates: boolean;
  work_location: string | null;
  notes: string;
}

export interface GeoPoint {
  lat: number;
  lng: number;
}

export interface FlightSegment {
  carrier: string;
  flight_number: string;
  origin: string;
  destination: string;
  depart: string;
  arrive: string;
  duration_min: number;
}

export interface FlightLeg {
  segments: FlightSegment[];
  duration_min: number;
  stops: number;
  max_layover_min: number;
}

/** Where to buy a live fare. Wayfinder never takes payment; the link opens the seller's site. */
export interface BookingOption {
  leg: string; // "outbound" | "inbound" | "round trip"
  provider: string;
  provider_type: "airline" | "third_party" | null;
  price: number | null;
  currency: string;
  price_verified: boolean;
  exact_flight: boolean;
  url: string;
}

export interface FlightOption {
  id: string;
  /** "train" = Indian Railways; then `cabin` is the IRCTC class (SL, 3A, 2A, 1A, CC, EC). */
  mode: "flight" | "train";
  outbound: FlightLeg;
  inbound: FlightLeg | null;
  price: number;
  currency: string;
  cabin: string;
  carriers: string[];
  source: string;
  booking_url: string;
  provider_ref: string;
  price_verified: boolean | null;
  observed_at: string | null;
  booking_options: BookingOption[];
  score: number;
  tags: string[];
  rationale: string;
}

export interface HotelOption {
  id: string;
  name: string;
  kind: string;
  stars: number;
  /** Guest rating out of 10; null when the source has none (never invented). */
  rating: number | null;
  /** 10 for Booking.com-style scores, 5 for TripAdvisor bubbles. */
  rating_scale: number;
  review_count: number;
  reviews_url: string;
  price_per_night: number;
  total_price: number;
  currency: string;
  location: GeoPoint;
  address: string;
  amenities: string[];
  distance_km: number;
  photo_url: string;
  booking_url: string;
  maps_url: string;
  website: string;
  phone: string;
  /** "openstreetmap" = real property, "booking.com" = live listing, "demo" = sample. */
  source: string;
  /** Fields that are estimates rather than source data, e.g. ["price", "stars"]. */
  estimated: string[];
  /** Live per-seller nightly prices (Booking.com, Agoda, Trip.com, hotel direct...). */
  booking_options: BookingOption[];
  price_checked_at: string | null;
  score: number;
  tags: string[];
  rationale: string;
}

export type PlaceCategory =
  | "sight" | "food" | "activity" | "nightlife" | "nature" | "kids" | "culture" | "shopping" | "wellness";

export interface Place {
  id: string;
  name: string;
  category: PlaceCategory;
  location: GeoPoint;
  /** Out of 5; null for Wikipedia / OpenStreetMap places, which have no ratings. */
  rating: number | null;
  review_count: number;
  /** 0-1 notability when there is no rating. */
  popularity: number;
  price_level: number;
  est_cost_per_person: number;
  duration_min: number;
  address: string;
  url: string;
  image_url: string;
  description: string;
  source: string;
  tags: string[];
}

export interface ScheduledActivity {
  place: Place;
  start: string;
  end: string;
  kind: "activity" | "meal";
  note: string;
}

export interface DayPlan {
  day: number;
  date: string;
  theme: string;
  area: string;
  activities: ScheduledActivity[];
  travel_km: number;
  center: GeoPoint | null;
}

export interface CostBreakdown {
  flights: number;
  lodging: number;
  activities: number;
  food: number;
  total: number;
  budget: number;
  currency: string;
}

export interface Itinerary {
  request: TripRequest;
  destination_center: GeoPoint | null;
  flight: FlightOption | null;
  flight_alternatives: FlightOption[];
  hotel: HotelOption | null;
  hotel_alternatives: HotelOption[];
  days: DayPlan[];
  costs: CostBreakdown;
  summary: string;
  highlights: string[];
  data_sources: Record<string, string>;
  version: number;
  generated_at: string;
}

export type StreamEvent =
  | { type: "session"; session_id: string }
  | { type: "agent"; agent: AgentName; status: AgentStatus; message: string }
  | { type: "message"; role: "assistant"; content: string }
  | { type: "itinerary"; data: Itinerary }
  | { type: "saved"; trip_id: string }
  | { type: "error"; message: string }
  | { type: "done" };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

export interface AgentState {
  status: AgentStatus;
  message: string;
  log: string[];
}

export interface Health {
  status: string;
  llm: string;
  providers: Record<string, "live" | "demo">;
}

export type TravelProfile = "driving" | "walking";

/** A road route from OSRM: [lat, lng] geometry plus distance/time for each leg between stops. */
export interface RoadRoute {
  distance_m: number;
  duration_s: number;
  legs: { distance_m: number; duration_s: number }[];
  geometry: [number, number][];
  source: string;
}
