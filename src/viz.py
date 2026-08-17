"""Folium map builders for route + shadow visualization."""
from __future__ import annotations

import math

import folium
import geopandas as gpd
import networkx as nx


def _latlon_dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine distance in metres between two (lat, lon) points."""
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = math.radians(b[0] - a[0])
    dlam = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _node_latlon(graph: nx.MultiDiGraph, node: int) -> tuple[float, float]:
    """Return (lat, lon) for a node, using the preserved WGS84 coords if the
    graph was reprojected to a metric CRS."""
    data = graph.nodes[node]
    if "_lat" in data:
        return data["_lat"], data["_lon"]
    return data["y"], data["x"]


def _path_latlon(graph: nx.MultiDiGraph, path: list[int]) -> list[tuple[float, float]]:
    return [_node_latlon(graph, n) for n in path]


def render_routes(
    graph: nx.MultiDiGraph,
    shortest: list[int],
    shade_route: list[int],
    shadow_layer: gpd.GeoSeries | None = None,
    zoom: int = 15,
    user_start: tuple[float, float] | None = None,
    user_end: tuple[float, float] | None = None,
) -> folium.Map:
    """Return a folium map with shortest (red) and shade (blue) routes.

    If `shadow_layer` is provided, its polygons are overlaid as translucent
    grey fills so the user can see *where* the model believes it's shaded.
    If `user_start` / `user_end` are provided, they are drawn as hollow grey
    crosses so the user sees the distance between where they clicked and
    where the router actually started/ended (graph-boundary snap).
    """
    coords = _path_latlon(graph, shortest)
    m = folium.Map(location=coords[0], zoom_start=zoom, tiles="OpenStreetMap")

    if shadow_layer is not None and len(shadow_layer) > 0:
        # Reproject to WGS84 for folium and simplify to keep the map light.
        wgs = shadow_layer.to_crs(4326).simplify(0.00005)
        folium.GeoJson(
            gpd.GeoSeries(wgs).__geo_interface__,
            style_function=lambda _f: {
                "fillColor": "#2b2b2b", "color": "#2b2b2b",
                "weight": 0, "fillOpacity": 0.25,
            },
            name="Shadow layer",
        ).add_to(m)

    # Solid red = shortest, dashed blue = shade — the dash pattern makes the
    # two routes distinguishable even for viewers with red-green colour blindness
    # or on a black-and-white printout.
    shortest_coords = _path_latlon(graph, shortest)
    shade_coords = _path_latlon(graph, shade_route)
    folium.PolyLine(
        shortest_coords, color="#d1495b", weight=5, opacity=0.9,
        tooltip="Shortest route (solid red)",
    ).add_to(m)
    folium.PolyLine(
        shade_coords, color="#2e86ab", weight=6, opacity=0.9,
        dash_array="10, 8",  # long dashes with a small gap
        tooltip="ShadowWalk route (dashed blue)",
    ).add_to(m)

    # Text-labelled tags at the route mid-points so the tooltip is not the
    # only affordance and printouts stay readable.
    if len(shortest_coords) >= 2:
        mid_s = shortest_coords[len(shortest_coords) // 2]
        folium.Marker(mid_s, icon=folium.DivIcon(
            html=('<div style="background:#d1495b;color:#fff;padding:2px 6px;'
                  'border-radius:3px;font:600 11px sans-serif;white-space:nowrap;">'
                  'Shortest</div>'))).add_to(m)
    if len(shade_coords) >= 2:
        mid_c = shade_coords[len(shade_coords) // 2]
        folium.Marker(mid_c, icon=folium.DivIcon(
            html=('<div style="background:#2e86ab;color:#fff;padding:2px 6px;'
                  'border-radius:3px;font:600 11px sans-serif;white-space:nowrap;">'
                  'ShadowWalk</div>'))).add_to(m)

    snapped_start = coords[0]
    snapped_end = _path_latlon(graph, shortest)[-1]
    folium.Marker(snapped_start, tooltip="Start (snapped to nearest street)",
                  icon=folium.Icon(color="green", icon="play")).add_to(m)
    folium.Marker(snapped_end, tooltip="End (snapped to nearest street)",
                  icon=folium.Icon(color="red", icon="flag")).add_to(m)

    # Optional hollow crosses at the user's original clicks — reveals any
    # graph-boundary snap so the map isn't quietly misleading.
    all_points = list(shortest_coords) + list(shade_coords)
    for label, click_pt, snapped in [
        ("Your start click", user_start, snapped_start),
        ("Your end click",   user_end,   snapped_end),
    ]:
        if click_pt is None:
            continue
        all_points.append(click_pt)
        # Only show the cross + connector line if the snap is meaningfully far.
        snap_m = _latlon_dist_m(click_pt, snapped)
        if snap_m < 30:
            continue
        folium.CircleMarker(
            click_pt, radius=7, color="#888", weight=2, fill=False,
            tooltip=f"{label} ({int(snap_m)} m from routed point)",
        ).add_to(m)
        folium.PolyLine(
            [click_pt, snapped], color="#888", weight=1.5,
            dash_array="4, 4", opacity=0.7,
        ).add_to(m)

    # Auto-fit so both routes AND click markers are on-screen.
    if len(all_points) >= 2:
        lats = [p[0] for p in all_points]
        lons = [p[1] for p in all_points]
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(30, 30))

    folium.LayerControl(collapsed=True).add_to(m)
    return m


def render_empty(center_lat: float, center_lon: float, zoom: int = 14) -> folium.Map:
    """A blank map for click-to-set start/end."""
    return folium.Map(location=(center_lat, center_lon), zoom_start=zoom, tiles="OpenStreetMap")
