"""OSM downloads + on-disk caching for walking graphs and buildings."""
from __future__ import annotations

import pickle
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pyproj
import shapely.ops as sops
from shapely.geometry import LineString

# Overpass mirrors, tried in order. The main endpoint gets rate-limited
# aggressively during peak hours; kumi.systems is the community backup.
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _try_mirrors(fetch_fn, retries_per_mirror: int = 2, backoff_s: float = 1.5):
    """Run `fetch_fn` against each Overpass mirror in sequence, with a short
    exponential backoff per mirror. Streamlit Cloud's shared IPs regularly hit
    Overpass rate limits; giving each mirror a couple of retries with a 1.5→3 s
    wait dramatically improves success on cold cloud starts.

    The first success returns its value. Raises the last exception on total
    failure so the caller can surface a plain-English error.
    """
    import time
    last_exc: Exception | None = None
    for url in _OVERPASS_MIRRORS:
        ox.settings.overpass_url = url
        for attempt in range(retries_per_mirror):
            try:
                return fetch_fn()
            except Exception as e:
                last_exc = e
                if attempt < retries_per_mirror - 1:
                    time.sleep(backoff_s * (2 ** attempt))
    raise last_exc  # type: ignore[misc]

from .config import (
    BUILDING_CACHE,
    CITIES,
    DEFAULT_BUILDING_HEIGHT_M,
    GRAPH_CACHE,
    LEVEL_HEIGHT_M,
    City,
)


def _graph_path(city: City) -> Path:
    return GRAPH_CACHE / f"{city.name}.pkl"


def _buildings_path(city: City) -> Path:
    return BUILDING_CACHE / f"{city.name}.parquet"


def get_city(key: str) -> City:
    if key not in CITIES:
        raise KeyError(f"Unknown city '{key}'. Known: {sorted(CITIES)}")
    return CITIES[key]


_TYPE_DEFAULTS_M: dict[str, float] = {
    # Taller building classes when OSM omits height AND levels.
    "commercial":   18.0,   # ~6 storeys
    "office":       24.0,   # ~8 storeys
    "retail":       12.0,
    "hotel":        24.0,
    "hospital":     18.0,
    "apartments":   15.0,
    "residential":  10.0,
    "house":         6.0,
    "garage":        3.0,
    "shed":          3.0,
    "warehouse":    10.0,
    "industrial":   12.0,
    "school":       10.0,
    "church":       15.0,
    "cathedral":    30.0,
    "tower":        40.0,
}


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).split()[0])
    except (ValueError, TypeError):
        return None


def _estimate_height(row) -> float:
    """Best-effort building height in metres.

    Priority order (each falls back if the previous is missing):
      1. explicit `height` (e.g. "45", "45 m")
      2. levels-based: `building:levels` × 3 m, plus `roof:height` if present
      3. type-based defaults (`commercial` → 18 m, etc.)
      4. project-wide default
    """
    h = _to_float(row.get("height"))
    if h and h > 0:
        return h

    levels = _to_float(row.get("building:levels"))
    if levels and levels > 0:
        min_level = _to_float(row.get("building:min_level")) or 0
        total_levels = max(1.0, levels - min_level)
        base = total_levels * LEVEL_HEIGHT_M
        roof_h = _to_float(row.get("roof:height")) or 0
        return base + roof_h

    btype = str(row.get("building", "")).lower()
    if btype in _TYPE_DEFAULTS_M:
        return _TYPE_DEFAULTS_M[btype]

    return DEFAULT_BUILDING_HEIGHT_M


def _reproject_graph(graph: nx.MultiDiGraph, dst_crs) -> nx.MultiDiGraph:
    """Reproject a lon/lat graph into a metric CRS in place.

    Preserves the original lon/lat on each node as `_lon` / `_lat` so folium
    (which needs WGS84) can still plot it.
    """
    project = pyproj.Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True).transform
    for _, data in graph.nodes(data=True):
        if "_lon" in data:
            continue  # already projected
        data["_lon"], data["_lat"] = data["x"], data["y"]
        data["x"], data["y"] = project(data["x"], data["y"])

    for u, v, data in graph.edges(data=True):
        if "geometry" in data:
            data["geometry"] = sops.transform(project, data["geometry"])
            data["length"] = data["geometry"].length
        else:
            xu, yu = graph.nodes[u]["x"], graph.nodes[u]["y"]
            xv, yv = graph.nodes[v]["x"], graph.nodes[v]["y"]
            data["length"] = ((xu - xv) ** 2 + (yu - yv) ** 2) ** 0.5
    graph.graph["crs"] = str(dst_crs)
    return graph


def load_city(
    city: City, refresh: bool = False
) -> tuple[nx.MultiDiGraph, gpd.GeoDataFrame]:
    """Load walking graph + buildings, both in a shared metric CRS.

    Cached to disk after the first call.
    """
    g_path, b_path = _graph_path(city), _buildings_path(city)

    if g_path.exists() and b_path.exists() and not refresh:
        with g_path.open("rb") as f:
            graph = pickle.load(f)
        buildings = gpd.read_parquet(b_path)
        return graph, buildings

    graph = _try_mirrors(lambda: ox.graph_from_place(
        city.query, network_type="walk", simplify=True))
    graph = ox.truncate.largest_component(graph, strongly=False)

    buildings = _try_mirrors(lambda: ox.features_from_place(
        city.query, tags={"building": True}))
    buildings = buildings[buildings.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    buildings["height"] = buildings.apply(_estimate_height, axis=1)

    utm_crs = buildings.estimate_utm_crs()
    buildings = buildings.to_crs(utm_crs)[["height", "geometry"]]
    graph = _reproject_graph(graph, utm_crs)

    with g_path.open("wb") as f:
        pickle.dump(graph, f)
    buildings.to_parquet(b_path)
    return graph, buildings


def _area_key(lat: float, lon: float, radius_m: int) -> str:
    return f"area_{lat:.4f}_{lon:.4f}_{radius_m}"


MS_DENSITY_THRESHOLD_PER_KM2 = 50  # below this we auto-fetch MS footprints


def load_area(
    lat: float, lon: float, radius_m: int,
    refresh: bool = False, use_ms_footprints: str | bool = "auto",
) -> tuple[nx.MultiDiGraph, gpd.GeoDataFrame]:
    """Load a radius around a point, cached to disk by (lat, lon, radius).

    `use_ms_footprints`:
      * ``"auto"`` (default) — fetch Microsoft Global Building Footprints only
        when OSM building density is thin (<50 per km² in the loaded circle).
        Adds missing footprints so under-mapped towns like Gangavathi still get
        a usable shadow layer.
      * ``True``  — always use MS Footprints (both add missing outlines and
        overlay heights where MS has them).
      * ``False`` — never fetch MS.
    """
    suffix = "_ms" if use_ms_footprints in (True, "auto") else ""
    key = _area_key(lat, lon, radius_m) + suffix
    g_path = GRAPH_CACHE / f"{key}.pkl"
    b_path = BUILDING_CACHE / f"{key}.parquet"

    if g_path.exists() and b_path.exists() and not refresh:
        with g_path.open("rb") as f:
            graph = pickle.load(f)
        buildings = gpd.read_parquet(b_path)
        return graph, buildings

    graph = _try_mirrors(lambda: ox.graph_from_point(
        (lat, lon), dist=radius_m, network_type="walk", simplify=True))
    graph = ox.truncate.largest_component(graph, strongly=False)

    buildings = _try_mirrors(lambda: ox.features_from_point(
        (lat, lon), tags={"building": True}, dist=radius_m))
    buildings = buildings[buildings.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    buildings["height"] = buildings.apply(_estimate_height, axis=1)

    utm_crs = buildings.estimate_utm_crs()
    buildings = buildings.to_crs(utm_crs)[["height", "geometry"]]

    # Density check — the loaded circle has area π·r²
    import math
    area_km2 = math.pi * (radius_m / 1000) ** 2
    density = len(buildings) / max(area_km2, 1e-6)
    should_use_ms = (
        use_ms_footprints is True
        or (use_ms_footprints == "auto" and density < MS_DENSITY_THRESHOLD_PER_KM2)
    )

    if should_use_ms:
        wgs = buildings.to_crs("EPSG:4326") if len(buildings) else None
        if wgs is not None and len(wgs):
            minx, miny, maxx, maxy = wgs.total_bounds
        else:
            # Fall back to a small bbox around the query point.
            dlat = radius_m / 111_320.0
            dlon = radius_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
            minx, miny, maxx, maxy = lon - dlon, lat - dlat, lon + dlon, lat + dlat

        from .ms_footprints import (
            load_ms_footprints_bbox,
            add_missing_buildings_from_ms,
            merge_heights_from_ms,
        )
        ms = load_ms_footprints_bbox(miny, minx, maxy, maxx, dst_crs=utm_crs)
        if len(ms) > 0:
            # (1) add outlines OSM is missing (heights default to 15 m)
            buildings = add_missing_buildings_from_ms(buildings, ms)
            # (2) overlay real MS heights on top wherever they exist
            buildings = merge_heights_from_ms(buildings, ms)

    graph = _reproject_graph(graph, utm_crs)

    with g_path.open("wb") as f:
        pickle.dump(graph, f)
    buildings.to_parquet(b_path)
    return graph, buildings


# --- Back-compat shims used by earlier code / notebooks -------------------
def load_walking_graph(city: City, refresh: bool = False) -> nx.MultiDiGraph:
    return load_city(city, refresh=refresh)[0]


def load_buildings(city: City, refresh: bool = False) -> gpd.GeoDataFrame:
    return load_city(city, refresh=refresh)[1]
