"""Tree cover from OpenStreetMap.

Two OSM signals get folded into the shade computation:

- `natural=tree` points → treated as small circular canopies (radius ~4 m).
- Green polygons (`landuse=forest`, `natural=wood`, `leisure=park`) →
  treated as continuous canopy inside the polygon.

Both are combined into a single "tree cover" GeoSeries in the same metric CRS
as the buildings / graph.
"""
from __future__ import annotations

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon

TREE_CANOPY_RADIUS_M = 4.0
GREEN_TAGS = {
    "natural": ["wood", "scrub"],
    "landuse": ["forest"],
    "leisure": ["park"],
}


def load_tree_cover_area(
    lat: float, lon: float, radius_m: int, dst_crs, refresh: bool = False
) -> gpd.GeoSeries:
    """Fetch OSM trees + green polygons around a point, projected to `dst_crs`.
    Cached to disk in data/city_graphs/trees_*.parquet."""
    from .config import GRAPH_CACHE
    cache = GRAPH_CACHE / f"trees_{lat:.4f}_{lon:.4f}_{radius_m}.parquet"
    if cache.exists() and not refresh:
        gdf = gpd.read_parquet(cache)
        return gdf.geometry.to_crs(dst_crs) if len(gdf) else gpd.GeoSeries([], crs=dst_crs)

    parts: list[gpd.GeoDataFrame] = []

    from .data_loader import _try_mirrors

    # Individual trees: point features buffered into small circles.
    try:
        trees = _try_mirrors(lambda: ox.features_from_point(
            (lat, lon), tags={"natural": "tree"}, dist=radius_m))
        pts = trees[trees.geometry.type == "Point"]
        if len(pts):
            pts = pts.to_crs(dst_crs)
            circles = pts.geometry.buffer(TREE_CANOPY_RADIUS_M)
            parts.append(gpd.GeoDataFrame(geometry=circles, crs=dst_crs))
    except Exception:
        pass  # tag may return nothing for this area

    # Green polygons
    try:
        greens = _try_mirrors(lambda: ox.features_from_point(
            (lat, lon), tags=GREEN_TAGS, dist=radius_m))
        polys = greens[greens.geometry.type.isin(["Polygon", "MultiPolygon"])]
        if len(polys):
            polys = polys.to_crs(dst_crs)
            parts.append(gpd.GeoDataFrame(geometry=polys.geometry, crs=dst_crs))
    except Exception:
        pass

    if not parts:
        # Persist an empty marker so future calls don't retry Overpass.
        gpd.GeoDataFrame(geometry=[], crs=dst_crs).to_parquet(cache)
        return gpd.GeoSeries([], crs=dst_crs)
    combined = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=dst_crs)
    combined.to_parquet(cache)
    return combined.geometry


def load_tree_cover_place(place: str, dst_crs) -> gpd.GeoSeries:
    """Same as load_tree_cover_area but for a whole named place."""
    parts: list[gpd.GeoSeries] = []
    try:
        trees = ox.features_from_place(place, tags={"natural": "tree"})
        pts = trees[trees.geometry.type == "Point"].to_crs(dst_crs)
        if len(pts):
            parts.append(pts.geometry.buffer(TREE_CANOPY_RADIUS_M))
    except Exception:
        pass
    try:
        greens = ox.features_from_place(place, tags=GREEN_TAGS)
        polys = greens[greens.geometry.type.isin(["Polygon", "MultiPolygon"])].to_crs(dst_crs)
        if len(polys):
            parts.append(polys.geometry)
    except Exception:
        pass
    if not parts:
        return gpd.GeoSeries([], crs=dst_crs)
    return pd.concat(parts, ignore_index=True)
