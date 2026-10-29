"""India market data: cities (airport + railway station), cost levels, business
venues, airlines, rupee formatting and seasonal travel advice.

Wayfinder is localized for travelers based in India: prices are in INR, domestic
trips consider Indian Railways alongside flights, and the agents are told about
Indian travel realities (monsoon, summer heat, altitude, vegetarian/Jain food).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

USD_TO_INR = 88.0  # used only to price sample inventory for destinations abroad


@dataclass(frozen=True)
class IndianCity:
    lat: float
    lng: float
    airport: str  # nearest commercial airport (IATA)
    station: str | None  # main railway station code; None = no direct rail link
    cost: float  # relative price level, 1.0 = typical Indian metro
    region: str  # metro | beach | desert | hills | himalaya | heritage


_C = IndianCity
INDIAN_CITIES: dict[str, IndianCity] = {
    # metros
    "delhi": _C(28.6139, 77.2090, "DEL", "NDLS", 1.1, "metro"),
    "mumbai": _C(19.0760, 72.8777, "BOM", "MMCT", 1.3, "metro"),
    "bengaluru": _C(12.9716, 77.5946, "BLR", "SBC", 1.1, "metro"),
    "chennai": _C(13.0827, 80.2707, "MAA", "MAS", 1.0, "metro"),
    "kolkata": _C(22.5726, 88.3639, "CCU", "HWH", 0.9, "metro"),
    "hyderabad": _C(17.3850, 78.4867, "HYD", "SC", 1.0, "metro"),
    "pune": _C(18.5204, 73.8567, "PNQ", "PUNE", 1.0, "metro"),
    "ahmedabad": _C(23.0225, 72.5714, "AMD", "ADI", 0.9, "metro"),
    "chandigarh": _C(30.7333, 76.7794, "IXC", "CDG", 0.9, "metro"),
    "gurugram": _C(28.4595, 77.0266, "DEL", "GGN", 1.1, "metro"),
    "noida": _C(28.5355, 77.3910, "DEL", "NDLS", 1.0, "metro"),
    "indore": _C(22.7196, 75.8577, "IDR", "INDB", 0.8, "metro"),
    "coimbatore": _C(11.0168, 76.9558, "CJB", "CBE", 0.85, "metro"),
    "guwahati": _C(26.1445, 91.7362, "GAU", "GHY", 0.85, "metro"),
    # Rajasthan & desert
    "jaipur": _C(26.9124, 75.7873, "JAI", "JP", 0.95, "desert"),
    "udaipur": _C(24.5854, 73.7125, "UDR", "UDZ", 1.1, "desert"),
    "jodhpur": _C(26.2389, 73.0243, "JDH", "JU", 0.9, "desert"),
    "jaisalmer": _C(26.9157, 70.9083, "JSA", "JSM", 0.9, "desert"),
    "pushkar": _C(26.4897, 74.5511, "JAI", "AII", 0.75, "desert"),
    "ranthambore": _C(26.0173, 76.3526, "JAI", "SWM", 1.0, "heritage"),
    # heritage & spiritual
    "agra": _C(27.1767, 78.0081, "AGR", "AGC", 0.85, "heritage"),
    "varanasi": _C(25.3176, 82.9739, "VNS", "BSB", 0.75, "heritage"),
    "amritsar": _C(31.6340, 74.8723, "ATQ", "ASR", 0.8, "heritage"),
    "lucknow": _C(26.8467, 80.9462, "LKO", "LKO", 0.8, "heritage"),
    "haridwar": _C(29.9457, 78.1642, "DED", "HW", 0.7, "heritage"),
    "khajuraho": _C(24.8318, 79.9199, "HJR", "KURJ", 0.8, "heritage"),
    "mysuru": _C(12.2958, 76.6394, "MYQ", "MYS", 0.8, "heritage"),
    "hampi": _C(15.3350, 76.4600, "HBX", "HPT", 0.7, "heritage"),
    "madurai": _C(9.9252, 78.1198, "IXM", "MDU", 0.8, "heritage"),
    "aurangabad": _C(19.8762, 75.3433, "IXU", "AWB", 0.8, "heritage"),
    "bhubaneswar": _C(20.2961, 85.8245, "BBI", "BBS", 0.8, "heritage"),
    # beaches & backwaters
    "goa": _C(15.4909, 73.8278, "GOI", "MAO", 1.2, "beach"),
    "kochi": _C(9.9312, 76.2673, "COK", "ERS", 0.9, "beach"),
    "alleppey": _C(9.4981, 76.3388, "COK", "ALLP", 0.9, "beach"),
    "varkala": _C(8.7379, 76.7163, "TRV", "VAK", 0.85, "beach"),
    "thiruvananthapuram": _C(8.5241, 76.9366, "TRV", "TVC", 0.85, "beach"),
    "pondicherry": _C(11.9416, 79.8083, "MAA", "PDY", 0.9, "beach"),
    "gokarna": _C(14.5479, 74.3188, "GOI", "GOK", 0.8, "beach"),
    "puri": _C(19.8135, 85.8312, "BBI", "PURI", 0.75, "beach"),
    "visakhapatnam": _C(17.6868, 83.2185, "VTZ", "VSKP", 0.85, "beach"),
    "mangaluru": _C(12.9141, 74.8560, "IXE", "MAQ", 0.85, "beach"),
    "andaman": _C(11.6234, 92.7265, "IXZ", None, 1.2, "beach"),
    # hill stations
    "shimla": _C(31.1048, 77.1734, "SLV", "SML", 0.9, "hills"),
    "rishikesh": _C(30.0869, 78.2676, "DED", "YNRK", 0.7, "hills"),
    "mussoorie": _C(30.4598, 78.0644, "DED", None, 0.9, "hills"),
    "nainital": _C(29.3919, 79.4542, "PGH", None, 0.85, "hills"),
    "darjeeling": _C(27.0410, 88.2663, "IXB", None, 0.85, "hills"),
    "munnar": _C(10.0889, 77.0595, "COK", None, 0.9, "hills"),
    "ooty": _C(11.4102, 76.6950, "CJB", "UAM", 0.85, "hills"),
    "kodaikanal": _C(10.2381, 77.4892, "IXM", None, 0.85, "hills"),
    "coorg": _C(12.3375, 75.8069, "IXE", None, 0.9, "hills"),
    "lonavala": _C(18.7546, 73.4062, "PNQ", "LNL", 0.9, "hills"),
    "mahabaleshwar": _C(17.9307, 73.6477, "PNQ", None, 0.9, "hills"),
    "shillong": _C(25.5788, 91.8933, "SHL", None, 0.85, "hills"),
    # Himalaya
    "manali": _C(32.2432, 77.1892, "KUU", None, 0.85, "himalaya"),
    "dharamshala": _C(32.2190, 76.3234, "DHM", None, 0.8, "himalaya"),
    "leh": _C(34.1526, 77.5771, "IXL", None, 1.0, "himalaya"),
    "srinagar": _C(34.0837, 74.7973, "SXR", None, 0.9, "himalaya"),
    "gangtok": _C(27.3389, 88.6065, "PYG", None, 0.9, "himalaya"),
}

ALIASES = {
    "new delhi": "delhi", "bombay": "mumbai", "bangalore": "bengaluru", "madras": "chennai",
    "calcutta": "kolkata", "gurgaon": "gurugram", "cochin": "kochi", "kerala": "kochi",
    "alappuzha": "alleppey", "trivandrum": "thiruvananthapuram", "puducherry": "pondicherry",
    "mysore": "mysuru", "vizag": "visakhapatnam", "mangalore": "mangaluru", "port blair": "andaman",
    "havelock": "andaman", "ladakh": "leh", "kashmir": "srinagar", "mcleodganj": "dharamshala",
    "north goa": "goa", "south goa": "goa", "panaji": "goa", "panjim": "goa", "sikkim": "gangtok",
}

HIGH_ALTITUDE = {"leh"}

# Common business venues/districts, so "stay near the venue" works offline.
VENUES: dict[str, tuple[float, float]] = {
    "bharat mandapam": (28.6170, 77.2430), "pragati maidan": (28.6170, 77.2430),
    "yashobhoomi": (28.5524, 77.0405), "aerocity": (28.5503, 77.1196),
    "cyber city": (28.4950, 77.0890), "connaught place": (28.6315, 77.2167),
    "bkc": (19.0662, 72.8654), "bandra kurla complex": (19.0662, 72.8654),
    "jio world centre": (19.0640, 72.8634), "bombay exhibition centre": (19.1530, 72.8530),
    "nesco": (19.1530, 72.8530), "lower parel": (19.0000, 72.8300), "powai": (19.1176, 72.9060),
    "whitefield": (12.9698, 77.7500), "biec": (13.0626, 77.4757), "electronic city": (12.8452, 77.6602),
    "manyata tech park": (13.0475, 77.6210), "mg road": (12.9756, 77.6050),
    "hitec city": (17.4435, 78.3772), "hitex": (17.4710, 78.3720), "gachibowli": (17.4401, 78.3489),
    "chennai trade centre": (13.0213, 80.1806), "omr": (12.9165, 80.2290),
    "biswa bangla convention centre": (22.5815, 88.4630), "salt lake sector v": (22.5735, 88.4331),
    "hinjewadi": (18.5912, 73.7389), "gift city": (23.1600, 72.6840), "mahatma mandir": (23.2335, 72.6460),
}

DOMESTIC_AIRLINES = [  # name, IATA code, price factor
    ("IndiGo", "6E", 0.92), ("Air India", "AI", 1.12), ("Air India Express", "IX", 0.86),
    ("SpiceJet", "SG", 0.85), ("Akasa Air", "QP", 0.88),
]
INTERNATIONAL_AIRLINES = [
    ("Air India", "AI", 1.0), ("IndiGo", "6E", 0.82), ("Emirates", "EK", 1.15), ("Qatar Airways", "QR", 1.12),
    ("Etihad Airways", "EY", 1.05), ("Singapore Airlines", "SQ", 1.2), ("Lufthansa", "LH", 1.15),
    ("Thai Airways", "TG", 0.95),
]
DOMESTIC_HUBS = ["DEL", "BOM", "BLR", "HYD", "MAA", "CCU"]
INTERNATIONAL_HUBS = ["DXB", "DOH", "AUH", "SIN", "IST", "FRA", "DEL", "BOM"]


def _key(name: str) -> str:
    k = name.split(",")[0].strip().lower()
    return ALIASES.get(k, k)


def indian_city(name: str) -> IndianCity | None:
    return INDIAN_CITIES.get(_key(name))


def is_indian(name: str) -> bool:
    return indian_city(name) is not None or name.strip().lower().endswith(", india")


def venue_point(name: str) -> tuple[float, float] | None:
    k = name.strip().lower()
    for venue, point in VENUES.items():
        if venue in k:
            return point
    return None


def format_inr(v: float) -> str:
    """₹ with Indian digit grouping: 1250000 -> ₹12,50,000."""
    n = int(round(abs(v)))
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{'-' if v < 0 else ''}₹{s}"


INDIA_CONTEXT = (
    "The traveler is based in India. Quote every price in Indian Rupees (₹) with Indian digit "
    "grouping (e.g. ₹1,25,000). Keep Indian travel realities in mind: Indian Railways/IRCTC trains "
    "for domestic routes, vegetarian and Jain food needs, modest dress at temples and gurdwaras, "
    "seasonal weather (summer heat Apr-Jun, monsoon Jun-Sep) and festival crowds."
)

_SEASONAL: dict[str, list[tuple[set[int], str]]] = {
    "beach": [
        ({6, 7, 8, 9}, "Monsoon season: heavy rain and rough seas - many beach shacks and water sports pause until October."),
        ({11, 12, 1}, "Peak season - book stays early; prices climb sharply around Christmas and New Year."),
    ],
    "desert": [
        ({4, 5, 6}, "Summer heat often crosses 40°C - sightsee early morning and late afternoon, and stay hydrated."),
        ({10, 11, 12, 1, 2, 3}, "Pleasant season for forts, palaces and desert camps - evenings get chilly, carry a layer."),
    ],
    "hills": [
        ({12, 1, 2}, "Cold with possible snowfall - pack warm layers; some roads can close at short notice."),
        ({7, 8}, "Monsoon landslides can disrupt hill roads - keep buffer time between transfers."),
    ],
    "himalaya": [
        ({11, 12, 1, 2, 3}, "Deep winter - many high passes are closed and temperatures drop well below zero; check road status."),
        ({7, 8}, "Monsoon can trigger landslides on mountain highways - keep a buffer day."),
    ],
    "heritage": [
        ({4, 5, 6}, "Hot afternoons - plan monuments for early morning and keep midday for indoor museums."),
        ({7, 8, 9}, "Monsoon showers - carry an umbrella; trains can run late."),
    ],
    "metro": [
        ({7, 8, 9}, "Monsoon showers can snarl city traffic - allow extra time for airport and station transfers."),
    ],
}


def seasonal_tips(destination: str, start: date) -> list[str]:
    city = indian_city(destination)
    if not city:
        return []
    tips = [t for months, t in _SEASONAL.get(city.region, []) if start.month in months]
    if _key(destination) in HIGH_ALTITUDE:
        tips.append("High altitude (3,500 m): rest for 24-48 hours after arriving to acclimatise before any exertion.")
    return tips
