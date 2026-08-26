"""ShadowWalk — Streamlit UI. Run: streamlit run app/streamlit_app.py"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CITIES
from src.data_loader import load_area
from src.directions import build_directions, format_markdown
from src.geocode import geocode
from src.metrics import summarize_route
from src.routing import route_between, snap_distance_m
from src.shade import compute_edge_shade
from src.sun import get_sun_position
from src.trees import load_tree_cover_area
from src.url_state import read_from_url, write_to_url
from src.viz import render_routes
from src.weather import fetch_conditions


st.set_page_config(
    page_title="ShadowWalk — shade-aware walking directions",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="auto",  # collapses automatically on narrow screens
)

# Mobile-friendly viewport tweak (Streamlit sets its own meta; this reinforces).
st.markdown(
    """<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">""",
    unsafe_allow_html=True,
)

# Sync from URL query params before any widget key is instantiated.
read_from_url(list(CITIES.keys()))

st.title("🌤️ ShadowWalk")
st.caption(
    "Find the shadiest walking path between two points — instead of the shortest. "
    "Built for hot Indian cities."
)

# ─── One-glance explainer ───────────────────────────────────────────────
with st.expander("How this works", expanded=False):
    st.markdown(
        """
1. **Downloads the walking network + buildings** for the city from OpenStreetMap.
2. **Computes the sun's position** for the hour you pick.
3. **Casts each building's shadow** on the ground (translate footprint away from
   the sun by `height / tan(elevation)`, take the convex hull with the original).
4. **Routes around sunlight** — Dijkstra with edge cost
   `length × (1 − α × shade_score)`.

The grey polygons on the map are the shadow layer. The red line is the fastest
walk. The blue line is what ShadowWalk suggests. Everything runs on your machine;
no Google Maps, no Mapbox, no keys. Zero cost.
"""
    )

# ─── Sidebar controls ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Setup")
    city_key = st.selectbox(
        "City", list(CITIES.keys()),
        format_func=lambda k: CITIES[k].query,
        key="city_selectbox",
    )
    city = CITIES[city_key]

    # Clear endpoints when the city changes — otherwise the previous city's
    # coordinates persist and snap to the new city's graph boundary, drawing
    # a nonsensical route.
    if st.session_state.get("_active_city") not in (None, city_key):
        for k in ("start", "end", "_last_click_consumed"):
            st.session_state.pop(k, None)
    st.session_state["_active_city"] = city_key

    date = st.date_input("Date", dt.date.today())

    # Setting the slider's session_state key BEFORE the widget lets buttons
    # (like "Try example route") pre-fill an hour and have the slider honour it.
    if "hour_slider" not in st.session_state:
        st.session_state["hour_slider"] = 14.0
    hour_float = st.slider(
        "Hour of day", 5.0, 20.0, step=0.5, format="%.1f h",
        help="Drag to watch routes morph as the sun moves across the sky.",
        key="hour_slider",
    )
    hh, mm = int(hour_float), int(round((hour_float - int(hour_float)) * 60))
    tm = dt.time(hh, mm)

    st.markdown("### Route preferences")
    # Plain-English α picker (replaces the α=0.7 jargon slider).
    if "preset_radio" not in st.session_state:
        st.session_state["preset_radio"] = "Balanced (small detour OK)"
    preset = st.radio(
        "How much detour will you accept for shade?",
        ["Fastest walk (no detour)",
         "Balanced (small detour OK)",
         "Coolest walk (bigger detour OK)"],
        key="preset_radio",
    )
    alpha = {"Fastest walk (no detour)": 0.0,
             "Balanced (small detour OK)": 0.6,
             "Coolest walk (bigger detour OK)": 0.9}[preset]

    with st.expander("Advanced options", expanded=False):
        use_trees = st.checkbox("Include tree cover", value=True)
        show_shadows = st.checkbox("Overlay shadow polygons", value=True)
        use_weather = st.checkbox("Weather-adjusted 'felt exposure'", value=True,
                                  help="Free Open-Meteo lookup — no API key.")
        radius_km = st.slider("Search radius around city centre (km)",
                              0.5, 3.0, 1.5, 0.1)

    st.markdown("### Endpoints")
    if "start" in st.session_state and "end" in st.session_state:
        # Small helper to reverse start↔end without losing the pins.
        if st.button("↔ Swap start / end"):
            st.session_state["start"], st.session_state["end"] = (
                st.session_state["end"], st.session_state["start"])
            st.rerun()
    def _apply_demo(city=city):
        """Callback: fires BEFORE widget instantiation, so we can set the
        hour_slider key without violating Streamlit's 'no post-instantiation
        writes' rule."""
        st.session_state["start"] = city.demo_start
        st.session_state["end"] = city.demo_end
        st.session_state["hour_slider"] = city.demo_hour
    st.button("🎯 Try example route", on_click=_apply_demo)
    if st.button("Reset click points"):
        for k in ("start", "end", "_last_click_consumed"):
            st.session_state.pop(k, None)
        st.rerun()

# ─── Cached loaders ─────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _load(city_key: str, radius_m: int):
    city = CITIES[city_key]
    with st.status(
        f"Loading {city.query} — first-time downloads take ~30–90 s "
        f"(OSM streets + ~1–3 k buildings). Cached to disk after this.",
        expanded=False,
    ):
        graph, buildings = load_area(city.lat, city.lon, radius_m)
        trees = load_tree_cover_area(city.lat, city.lon, radius_m, dst_crs=buildings.crs)
    return graph, buildings, trees


@st.cache_data(show_spinner="Casting shadows…")
def _shade_for_hour(city_key: str, radius_m: int, hour_bucket: str, use_trees: bool):
    """Recomputed only when the hour bucket (rounded to the minute) changes."""
    graph, buildings, trees = _load(city_key, radius_m)
    city = CITIES[city_key]
    when = pd.Timestamp(hour_bucket, tz=city.tz)
    az, elev = get_sun_position(city.lat, city.lon, when)
    compute_edge_shade(
        graph, buildings, az, elev,
        tree_cover=(trees if use_trees else None),
    )
    return graph, az, elev, when


@st.cache_data(show_spinner=False)
def _weather(lat: float, lon: float, hour_bucket: str, tz: str):
    when = pd.Timestamp(hour_bucket, tz=tz)
    return fetch_conditions(lat, lon, when)


# ─── Endpoint picker ────────────────────────────────────────────────────
radius_m = int(radius_km * 1000)
when = pd.Timestamp(dt.datetime.combine(date, tm), tz=city.tz)
hour_bucket = when.strftime("%Y-%m-%d %H:%M")

# ─── Address search + geolocation (two ways to set endpoints besides clicking) ─
def _bbox_around_city(c, span_deg=0.05):
    """Nominatim viewbox: min_lon, min_lat, max_lon, max_lat."""
    return (c.lon - span_deg, c.lat - span_deg, c.lon + span_deg, c.lat + span_deg)


search_col, geo_col = st.columns([3, 1])
with search_col:
    with st.form("addr_search", clear_on_submit=False):
        cols = st.columns([4, 1, 1])
        query = cols[0].text_input(
            "Search a place inside the city (e.g. 'Marina Beach', 'India Gate')",
            key="addr_query", label_visibility="collapsed",
            placeholder=f"Search a place inside {city.query} …",
        )
        set_target = cols[1].selectbox(
            "as", ["Start", "End"], key="addr_target", label_visibility="collapsed",
        )
        submitted = cols[2].form_submit_button("Search")
    if submitted and query.strip():
        results = geocode(query, viewbox=_bbox_around_city(city))
        if not results:
            st.warning(f"No place found for “{query}”. Try a more specific name.")
        else:
            hit = results[0]
            latlon = (hit["lat"], hit["lon"])
            st.session_state["start" if set_target == "Start" else "end"] = latlon
            st.success(f"📍 {set_target} → {hit['display_name']}")
            st.rerun()

with geo_col:
    # HTML+JS bridge for browser geolocation. When the user clicks the button,
    # the browser prompts for location, then reloads the page with lat/lon in
    # the URL — Streamlit picks it up via read_from_url on the next run.
    st.markdown(
        """
<div style="text-align:right;">
  <button onclick="
    if (!navigator.geolocation) { alert('Geolocation not supported by this browser.'); return; }
    navigator.geolocation.getCurrentPosition(
      p => {
        const q = 'start=' + p.coords.latitude.toFixed(5) + ',' + p.coords.longitude.toFixed(5);
        try {
          const url = new URL(window.parent.location.href);
          url.searchParams.set('start', p.coords.latitude.toFixed(5) + ',' + p.coords.longitude.toFixed(5));
          window.parent.location.href = url.toString();
        } catch (e) {
          // Streamlit iframe may block cross-origin parent access — fall back
          // to copying a shareable URL so the user can paste it manually.
          const share = 'https://shadowwalk.streamlit.app/?' + q;
          navigator.clipboard.writeText(share).then(
            () => alert('Location copied as URL — paste it into the address bar:\\n\\n' + share),
            () => alert('Please paste this in the address bar:\\n\\n' + share)
          );
        }
      },
      e => alert('Could not get location: ' + e.message)
    );"
    style="background:#2e86ab;color:#fff;border:0;padding:6px 12px;border-radius:4px;font-size:14px;cursor:pointer;">
    📍 Use my location as start
  </button>
</div>
""",
        unsafe_allow_html=True,
    )

if "start" not in st.session_state:
    st.info(
        "👉 Click **inside the shaded circle** once to set **START**, then click "
        "again for **END**. Only the area inside the circle is loaded for routing.  \n"
        "Or hit the **Try example route** button in the sidebar to see it work "
        "on a known-good pair."
    )
elif "end" not in st.session_state:
    st.info("👉 One more click inside the circle to set **END**.")


def _circle_bounds(lat, lon, radius_m):
    """Lat/lon bounding box of a circle of the given radius (metres)."""
    import math
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
    return [[lat - dlat, lon - dlon], [lat + dlat, lon + dlon]]


base = folium.Map(tiles="OpenStreetMap")
# Frame the picker to exactly the loaded neighbourhood so the clickable area
# matches the routable area — this is what stops clicks from snapping 1+ km away.
base.fit_bounds(_circle_bounds(city.lat, city.lon, radius_m))
# Draw the loaded-area boundary so users can see where they may click.
folium.Circle(
    location=(city.lat, city.lon), radius=radius_m,
    color="#2e86ab", weight=2, fill=True, fill_opacity=0.05,
    dash_array="6, 6",
    tooltip=f"Routing is loaded within {radius_km:.1f} km of here",
).add_to(base)
if "start" in st.session_state:
    folium.Marker(st.session_state["start"], tooltip="Start",
                  icon=folium.Icon(color="green", icon="play")).add_to(base)
if "end" in st.session_state:
    folium.Marker(st.session_state["end"], tooltip="End",
                  icon=folium.Icon(color="red", icon="flag")).add_to(base)

click = st_folium(base, height=420, width=None, key="picker",
                  returned_objects=["last_clicked"])

# `st_folium` remembers the last click across reruns; without deduping we
# would apply the same click twice — first as START, then immediately as
# END on the next rerun. Compare against the last coord we already consumed.
def _haversine_m(lat1, lon1, lat2, lon2):
    import math
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


new_click = click.get("last_clicked") if click else None
if new_click:
    latlon = (new_click["lat"], new_click["lng"])
    if st.session_state.get("_last_click_consumed") != latlon:
        st.session_state["_last_click_consumed"] = latlon
        # Reject clicks outside the loaded circle up front — this is what
        # prevents the router from silently snapping to a distant boundary
        # node and drawing a route that starts kilometres from the pin.
        dist_from_centre = _haversine_m(latlon[0], latlon[1], city.lat, city.lon)
        if dist_from_centre > radius_m:
            st.toast(
                f"That click is {dist_from_centre/1000:.1f} km from the centre — "
                f"outside the loaded {radius_km:.1f} km circle. Click inside the "
                f"circle, or raise the search radius in Advanced options.",
                icon="⚠️",
            )
        elif "start" not in st.session_state:
            st.session_state["start"] = latlon
            st.rerun()
        elif "end" not in st.session_state:
            st.session_state["end"] = latlon
            st.rerun()
        else:
            # Both already set — a fresh click starts a new selection so the
            # user can re-pick without hitting Reset first.
            st.session_state["start"] = latlon
            st.session_state.pop("end", None)
            st.rerun()

# ─── Route computation ──────────────────────────────────────────────────
if "start" in st.session_state and "end" in st.session_state:
    s_lat, s_lon = st.session_state["start"]
    e_lat, e_lon = st.session_state["end"]

    try:
        graph, az, elev, resolved_when = _shade_for_hour(
            city_key, radius_m, hour_bucket, use_trees,
        )
    except Exception as e:
        st.error(
            f"Couldn't load {city.query} from OpenStreetMap. This usually means "
            f"the Overpass API is temporarily rate-limiting us; try again in a "
            f"minute. (Underlying error: {type(e).__name__})"
        )
        st.stop()

    weather = _weather(city.lat, city.lon, hour_bucket, city.tz) if use_weather else None
    caption_bits = [
        f"☀️ **Sun** {az:.0f}° azimuth, {elev:.0f}° above the horizon "
        f"({resolved_when.strftime('%d %b %Y · %H:%M %Z')})"
    ]
    if weather is not None:
        caption_bits.append(f"🌡️ **Weather**: {weather.plain_english()}")
    st.markdown("  \n".join(caption_bits))

    # Warn if either click is materially far from the nearest graph node —
    # otherwise the router silently snaps to the graph boundary and the map
    # below shows a walk that starts/ends kilometres from the user's pin.
    snap_s = snap_distance_m(graph, s_lat, s_lon)
    snap_e = snap_distance_m(graph, e_lat, e_lon)
    if max(snap_s, snap_e) > 300:
        st.warning(
            f"⚠️ **One of your points is far from the loaded neighbourhood** — "
            f"start snapped by **{snap_s:.0f} m**, end by **{snap_e:.0f} m**. "
            f"The route below starts and ends at those snapped points, not at "
            f"your original clicks. Either:  \n"
            f"• click closer to the current map view,  \n"
            f"• increase **Search radius** in the sidebar → Advanced options, "
            f"or  \n"
            f"• hit **🎯 Try example route** for a route guaranteed to be "
            f"inside the loaded area."
        )

    try:
        shortest = route_between(graph, s_lat, s_lon, e_lat, e_lon, alpha=0.0)
        shade = route_between(graph, s_lat, s_lon, e_lat, e_lon, alpha=alpha)
    except Exception as e:
        st.error(
            "🚫 **No walking path found between those two points.**  \n"
            "This usually means one endpoint fell outside the loaded neighbourhood "
            "or into water. Try:  \n"
            "• clicking closer to a visible street,  \n"
            "• increasing the search radius in the sidebar,  \n"
            "• or hitting **Try example route** to reset to a known-good pair.  \n\n"
            f"_(technical: {type(e).__name__})_"
        )
        st.stop()

    shadow_layer = graph.graph.get("shadow_layer") if show_shadows else None
    fmap = render_routes(
        graph, shortest, shade,
        shadow_layer=shadow_layer,
        user_start=(s_lat, s_lon), user_end=(e_lat, e_lon),
    )
    st_folium(fmap, height=520, width=None, key="routes", returned_objects=[])

    a = summarize_route(graph, shortest, alpha=0.0)
    b = summarize_route(graph, shade, alpha=alpha)
    if weather is not None:
        m = weather.heat_multiplier()
        a = a.apply_weather(m)
        b = b.apply_weather(m)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("🔴 Shortest")
        st.metric("Distance",         f"{a.distance_m:.0f} m", f"{a.walk_time_min:.1f} min walk")
        st.metric("Shaded",           f"{100*a.shaded_fraction:.1f}%")
        st.metric("Sun exposure",     f"{a.sun_exposure_min:.1f} min")
        if a.felt_heat_min is not None:
            st.metric("Felt heat load", f"{a.felt_heat_min:.1f} min-eq")
    with c2:
        st.subheader("🔵 ShadowWalk")
        st.metric("Distance",         f"{b.distance_m:.0f} m", f"{b.walk_time_min:.1f} min walk")
        st.metric("Shaded",           f"{100*b.shaded_fraction:.1f}%")
        st.metric("Sun exposure",     f"{b.sun_exposure_min:.1f} min")
        if b.felt_heat_min is not None:
            st.metric("Felt heat load", f"{b.felt_heat_min:.1f} min-eq")
    with c3:
        st.subheader("✨ Difference")
        d_dist  = b.distance_m - a.distance_m
        d_shade = 100 * (b.shaded_fraction - a.shaded_fraction)
        d_exp   = b.sun_exposure_min - a.sun_exposure_min
        st.metric("Extra distance", f"{d_dist:+.0f} m",
                  f"{100*d_dist/max(a.distance_m,1):+.1f}%")
        st.metric("Extra shade", f"{d_shade:+.1f} pp")
        st.metric("Sun exposure saved", f"{-d_exp:.1f} min",
                  delta_color=("normal" if d_exp <= 0 else "inverse"))
        if a.felt_heat_min is not None and b.felt_heat_min is not None:
            st.metric("Felt heat saved",
                      f"{(a.felt_heat_min - b.felt_heat_min):.1f} min-eq")

    # ─── Turn-by-turn directions ────────────────────────────────────────
    dir_tab_short, dir_tab_shade = st.tabs(
        ["🚶 Directions — Shortest", "🌤️ Directions — ShadowWalk"]
    )
    with dir_tab_short:
        st.markdown(format_markdown(build_directions(graph, shortest, alpha=0.0)))
    with dir_tab_shade:
        st.markdown(format_markdown(build_directions(graph, shade, alpha=alpha)))

    # ─── Share link — reflects current state in the URL ─────────────────
    write_to_url(
        city_key, hour_float, alpha,
        st.session_state.get("start"), st.session_state.get("end"),
    )
    st.caption("🔗 The URL above now encodes this exact view — copy the address "
               "bar to share this route with someone.")

# ─── Footer ─────────────────────────────────────────────────────────────
st.markdown(
    """
---
<div style="text-align:center; opacity:0.65; font-size:0.85em;">
ShadowWalk · open source on
<a href="https://github.com/Char1an/shadowwalk" target="_blank">GitHub</a>
· built with OSM, pvlib &amp; Streamlit · zero-cost stack, zero API keys ·
building heights and shadows are estimates — treat the routes as suggestions, not gospel
</div>
""",
    unsafe_allow_html=True,
)
