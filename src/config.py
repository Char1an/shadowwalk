"""Global configuration: cities, defaults, paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
GRAPH_CACHE = DATA_DIR / "city_graphs"
BUILDING_CACHE = DATA_DIR / "buildings"
MS_FOOTPRINTS = DATA_DIR / "ms_footprints"

for _p in (GRAPH_CACHE, BUILDING_CACHE, MS_FOOTPRINTS):
    _p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class City:
    name: str                   # canonical key, used for cache filenames
    query: str                  # what osmnx.graph_from_place expects
    lat: float                  # approximate centre, used for sun computation defaults
    lon: float
    tz: str                     # IANA timezone
    # A known-good demo route (start, end) inside the city and a good
    # demo hour of the day for that neighbourhood. Powers the
    # "Try this example" button in the UI.
    demo_start: tuple[float, float]
    demo_end: tuple[float, float]
    demo_hour: float


# City centres are set to the midpoint of the demo route so the loaded
# neighbourhood always contains it — the "Try example route" button then
# works out-of-the-box without hitting graph-boundary snapping.
CITIES: dict[str, City] = {
    # Coastal humid — Chennai T. Nagar
    "chennai":   City("chennai",   "Chennai, India",     13.0418, 80.2345, "Asia/Kolkata",
                     demo_start=(13.0440, 80.2320), demo_end=(13.0395, 80.2370), demo_hour=8.0),
    # Northern dry-heat capital — Connaught Place
    "delhi":     City("delhi",     "New Delhi, India",   28.6315, 77.2170, "Asia/Kolkata",
                     demo_start=(28.6345, 77.2140), demo_end=(28.6285, 77.2200), demo_hour=9.0),
    # Western dry-heat, first Indian city with a Heat Action Plan — Ashram Road
    "ahmedabad": City("ahmedabad", "Ahmedabad, India",   23.0330, 72.5685, "Asia/Kolkata",
                     demo_start=(23.0360, 72.5660), demo_end=(23.0295, 72.5710), demo_hour=17.0),
    # Bengaluru MG Road / Brigade Rd — cooler climate but still a heat-index concern
    "bengaluru": City("bengaluru", "Bengaluru, India",   12.9725, 77.6035, "Asia/Kolkata",
                     demo_start=(12.9750, 77.6070), demo_end=(12.9700, 77.6000), demo_hour=8.5),
    # Hyderabad Charminar — old-city Deccan heat
    "hyderabad": City("hyderabad", "Hyderabad, India",   17.3630, 78.4765, "Asia/Kolkata",
                     demo_start=(17.3600, 78.4740), demo_end=(17.3660, 78.4790), demo_hour=17.0),
    # Mumbai Fort — dense Art Deco district near the coast
    "mumbai":    City("mumbai",    "Mumbai, India",      18.9300, 72.8327, "Asia/Kolkata",
                     demo_start=(18.9330, 72.8300), demo_end=(18.9270, 72.8355), demo_hour=9.0),
    # Kolkata Esplanade / New Market — humid, historic mid-rises
    "kolkata":   City("kolkata",   "Kolkata, India",     22.5647, 88.3510, "Asia/Kolkata",
                     demo_start=(22.5680, 88.3480), demo_end=(22.5615, 88.3540), demo_hour=8.5),
    # Jaipur Pink City — heritage lanes with mid-rise havelis
    "jaipur":    City("jaipur",    "Jaipur, India",      26.9238, 75.8215, "Asia/Kolkata",
                     demo_start=(26.9265, 75.8250), demo_end=(26.9210, 75.8180), demo_hour=17.0),
    # Mysuru (Karnataka) — heritage city; Devaraja Market / Sayyaji Rao Rd
    # around Mysore Palace, well-mapped in OSM, hot dry summers (35 °C+)
    "mysuru":    City("mysuru",    "Mysuru, Karnataka, India",
                     12.3080, 76.6560, "Asia/Kolkata",
                     demo_start=(12.3055, 76.6535), demo_end=(12.3115, 76.6595), demo_hour=17.0),
}

# Shade / routing defaults
DEFAULT_ALPHA = 0.7            # shade preference, 0..1
SAMPLE_SPACING_M = 5.0         # distance between shade sample points along an edge
BUILDING_SEARCH_RADIUS_M = 50  # how far to look for potential blockers
DEFAULT_BUILDING_HEIGHT_M = 15.0  # ~5 storeys; better proxy in dense Indian/ME cities
LEVEL_HEIGHT_M = 3.0           # for OSM building:levels fallback
WALK_SPEED_MPS = 1.35          # ~4.9 km/h, standard pedestrian speed
