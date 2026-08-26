"""Per-edge shade score via precomputed 2D shadow polygons.

Algorithm
---------
1. For each building of height h, translate its footprint in the direction
   *opposite* the sun by distance h / tan(elevation). The convex hull of the
   original + translated footprints is that building's ground shadow.
2. Union all shadow polygons (plus any optional canopy polygons) into a
   single spatial index (STRtree).
3. For each street edge, sample points every ~5 m; the shade score is the
   fraction of sample points that fall inside the shadow layer.

This is both more geometrically correct than centroid-direction ray casting
and much faster — shadow polygons are computed once per (city, hour), and
per-point lookups are a single `contains` query on a spatial index.
"""
from __future__ import annotations

import math

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .config import SAMPLE_SPACING_M

MAX_SHADOW_LENGTH_M = 500.0  # cap shadow length for near-horizon sun


def _sample_points(line: LineString, spacing: float) -> list[Point]:
    """Sample points every `spacing` metres along a line, endpoints included."""
    if line.length == 0:
        return [Point(line.coords[0])]
    n = max(2, int(math.ceil(line.length / spacing)) + 1)
    return [line.interpolate(d) for d in np.linspace(0.0, line.length, n)]


def _shadow_polygon(footprint, height: float, dx: float, dy: float) -> Polygon | None:
    """Ground shadow of a single building.

    `dx, dy` is the ground vector by which each footprint vertex is
    translated to represent the shadow tip. The final shadow is the convex
    hull of the original footprint and its translation — this correctly
    covers everything between the building and the shadow tip regardless of
    footprint shape.
    """
    if footprint.is_empty or height <= 0:
        return None
    shifted = translate(footprint, xoff=dx, yoff=dy)
    try:
        return unary_union([footprint, shifted]).convex_hull
    except Exception:
        return None


def build_shadow_layer(
    buildings: gpd.GeoDataFrame,
    sun_azimuth_deg: float,
    sun_elevation_deg: float,
    tree_cover: gpd.GeoSeries | None = None,
) -> gpd.GeoSeries:
    """Return a GeoSeries of shadow polygons in the buildings' CRS.

    At night (sun below horizon) returns an empty series — callers should
    treat everywhere as shaded in that case.
    """
    if sun_elevation_deg <= 0:
        return gpd.GeoSeries([], crs=buildings.crs)

    # Vector pointing AWAY from the sun (where each building casts its shadow).
    # In the projected metric CRS: +x is east, +y is north. Sun azimuth is
    # measured clockwise from north, so sun-direction is (sin(az), cos(az))
    # and the anti-sun direction (where shadows lie) is (-sin(az), -cos(az)).
    az = math.radians(sun_azimuth_deg)
    length_multiplier = 1.0 / max(math.tan(math.radians(sun_elevation_deg)), 1e-3)
    unit_dx, unit_dy = -math.sin(az), -math.cos(az)

    shadows = []
    for footprint, h in zip(buildings.geometry.values, buildings["height"].values):
        if footprint is None or footprint.is_empty:
            continue
        if not footprint.is_valid:
            footprint = footprint.buffer(0)  # standard shapely repair
            if footprint.is_empty or not footprint.is_valid:
                continue
        # Cap the actual shadow length in METRES per building — otherwise a
        # 100 m tower at 3° sun would extrude a ~2 km streak across the map.
        h_f = float(h)
        shadow_len_m = min(MAX_SHADOW_LENGTH_M, h_f * length_multiplier)
        try:
            s = _shadow_polygon(footprint, h_f, unit_dx * shadow_len_m, unit_dy * shadow_len_m)
        except Exception:
            continue
        if s is not None and not s.is_empty:
            shadows.append(s)

    if tree_cover is not None and len(tree_cover) > 0:
        shadows.extend(tree_cover.values)

    if not shadows:
        return gpd.GeoSeries([], crs=buildings.crs)
    # Tiny buffer (0.5 m) absorbs floating-point boundary error and gives a
    # small tolerance for sample points that sit exactly on a curb.
    return gpd.GeoSeries(shadows, crs=buildings.crs).buffer(0.5)


def compute_edge_shade(
    graph: nx.MultiDiGraph,
    buildings: gpd.GeoDataFrame,
    sun_azimuth_deg: float,
    sun_elevation_deg: float,
    spacing: float = SAMPLE_SPACING_M,
    tree_cover: gpd.GeoSeries | None = None,
) -> nx.MultiDiGraph:
    """Populate a `shade_score` (0..1) attribute on every edge, in place."""
    if sun_elevation_deg <= 0:
        # Night — everything is "shaded"; routing degenerates to shortest path.
        # Clear any stale daytime shadow layer left over from a previous call
        # so downstream viz doesn't paint sun-time shadows on a night map.
        for _, _, data in graph.edges(data=True):
            data["shade_score"] = 1.0
        graph.graph["shadow_layer"] = gpd.GeoSeries([], crs=buildings.crs)
        return graph

    shadow_layer = build_shadow_layer(buildings, sun_azimuth_deg, sun_elevation_deg, tree_cover)
    if len(shadow_layer) == 0:
        for _, _, data in graph.edges(data=True):
            data["shade_score"] = 0.0
        graph.graph["shadow_layer"] = shadow_layer
        return graph

    geoms = list(shadow_layer.values)
    tree = STRtree(geoms)

    for u, v, _, data in graph.edges(keys=True, data=True):
        line: LineString | None = data.get("geometry")
        if line is None:
            nu, nv = graph.nodes[u], graph.nodes[v]
            line = LineString([(nu["x"], nu["y"]), (nv["x"], nv["y"])])

        samples = _sample_points(line, spacing)
        shaded = 0
        for p in samples:
            hits = tree.query(p)
            if any(geoms[i].covers(p) for i in hits):
                shaded += 1
        data["shade_score"] = shaded / len(samples)

    # Stash shadow layer on the graph for downstream visualization.
    graph.graph["shadow_layer"] = shadow_layer
    return graph
