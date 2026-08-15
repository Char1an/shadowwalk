"""Shade-weighted shortest-path routing."""
from __future__ import annotations

import networkx as nx
import osmnx as ox
import pyproj

from .config import DEFAULT_ALPHA


def make_weight_fn(alpha: float = DEFAULT_ALPHA):
    """Return an edge-weight function: length * (1 - alpha * shade_score).

    alpha = 0 → pure shortest path.
    alpha = 1 → maximally shade-seeking (may detour heavily).
    """
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be in [0, 1], got {alpha}")

    def _edge_cost(d: dict) -> float:
        shade = d.get("shade_score", 0.0)
        length = d.get("length", 0.0)
        return length * (1.0 - alpha * shade) + 1e-6

    def weight(u, v, data):
        # For a MultiDiGraph, networkx hands us {key: edge_data}; for a plain
        # (Di)Graph it hands us the edge dict directly. Handle both.
        if data and all(isinstance(v_, dict) for v_ in data.values()):
            return min(_edge_cost(ed) for ed in data.values())
        return _edge_cost(data)

    return weight


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in metres."""
    import math
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def snap_distance_m(graph: nx.MultiDiGraph, lat: float, lon: float) -> float:
    """How far, in metres, is the user's click from the nearest graph node?

    Large numbers mean the click landed outside the loaded neighbourhood and
    the router will silently snap to a distant boundary node — the caller
    should surface that to the user."""
    node = nearest_node(graph, lat, lon)
    n = graph.nodes[node]
    # Prefer the preserved WGS84 coords when the graph was reprojected.
    if "_lat" in n:
        n_lat, n_lon = n["_lat"], n["_lon"]
    else:
        n_lat, n_lon = n["y"], n["x"]
    return _haversine_m(lat, lon, n_lat, n_lon)


def nearest_node(graph: nx.MultiDiGraph, lat: float, lon: float) -> int:
    """Nearest graph node to a (lat, lon) point, honouring the graph's CRS.

    If `load_area` / `load_city` reprojected the graph to a metric CRS, the
    node `x`/`y` attributes are UTM metres and we need to project the query
    into that same CRS before searching. Otherwise `osmnx.nearest_nodes`
    would treat the WGS84 (lon, lat) values as if they were metres.
    """
    crs = graph.graph.get("crs")
    if crs is None or str(crs).upper() in ("EPSG:4326", "WGS84"):
        return ox.distance.nearest_nodes(graph, X=lon, Y=lat)

    project = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    x, y = project(lon, lat)

    # Manual nearest-node search in the target CRS.
    best_node, best_d2 = None, float("inf")
    for node, data in graph.nodes(data=True):
        d2 = (data["x"] - x) ** 2 + (data["y"] - y) ** 2
        if d2 < best_d2:
            best_d2, best_node = d2, node
    return best_node


def shortest_path(
    graph: nx.MultiDiGraph, source: int, target: int, alpha: float = 0.0
) -> list[int]:
    """Dijkstra path with the shade-weighted metric."""
    weight = make_weight_fn(alpha)
    return nx.shortest_path(graph, source=source, target=target, weight=weight)


def route_between(
    graph: nx.MultiDiGraph,
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    alpha: float = 0.0,
) -> list[int]:
    """Convenience: coords → node ids → path."""
    s = nearest_node(graph, start_lat, start_lon)
    t = nearest_node(graph, end_lat, end_lon)
    return shortest_path(graph, s, t, alpha=alpha)
