"""Microsoft Global ML Building Footprints — a source of *real* heights.

Microsoft publishes ~1.5 billion building footprints with an estimated
`height` attribute, tiled by web-mercator quadkey at zoom 9 and packaged as
one `.csv.gz` per tile. We only download the handful of tiles that touch our
search box, decode the JSONL GeoJSON rows, and cache the result.

The index CSV lives at:
    https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv

Each row is (Location, QuadKey, Url, Size, UploadDate). We match by
quadkey, download the tiles inside our bounding box, and stitch them
together.

If the download fails (offline, rate-limited), the caller falls back to
OSM-only heights — the router still works, just with the coarser defaults.
"""
from __future__ import annotations

import gzip
import io
import json
import math
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import box, shape

from .config import DATA_DIR

MS_CACHE = DATA_DIR / "ms_footprints"
MS_CACHE.mkdir(parents=True, exist_ok=True)
INDEX_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
QUADKEY_ZOOM = 9


# --- quadkey math (Bing tile system, zoom 9) ------------------------------
def _latlon_to_tile(lat: float, lon: float, zoom: int = QUADKEY_ZOOM) -> tuple[int, int]:
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def _tile_to_quadkey(x: int, y: int, zoom: int = QUADKEY_ZOOM) -> str:
    key = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask: digit += 1
        if y & mask: digit += 2
        key.append(str(digit))
    return "".join(key)


def quadkeys_for_bbox(
    min_lat: float, min_lon: float, max_lat: float, max_lon: float,
) -> list[str]:
    """All zoom-9 quadkeys covering a bounding box."""
    x0, y1 = _latlon_to_tile(max_lat, min_lon)
    x1, y0 = _latlon_to_tile(min_lat, max_lon)
    keys = []
    for x in range(min(x0, x1), max(x0, x1) + 1):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            keys.append(_tile_to_quadkey(x, y))
    return keys


# --- dataset index --------------------------------------------------------
@lru_cache(maxsize=1)
def _dataset_index() -> pd.DataFrame:
    """Fetch and cache the tile-URL index."""
    local = MS_CACHE / "dataset-links.csv"
    if not local.exists():
        r = requests.get(INDEX_URL, timeout=30)
        r.raise_for_status()
        local.write_bytes(r.content)
    return pd.read_csv(local)


def _urls_for_quadkeys(quadkeys: list[str]) -> pd.DataFrame:
    idx = _dataset_index()
    return idx[idx["QuadKey"].astype(str).isin(quadkeys)]


# --- tile decode ----------------------------------------------------------
def _decode_tile(local: Path) -> gpd.GeoDataFrame:
    """Parse a `.csv.gz` MS-footprints tile.

    Despite the file extension, tiles are actually JSONL (one GeoJSON
    Feature per line). Regions without height coverage (e.g. India) report
    `height = -1.0`, which we drop rather than treat as ground level.
    """
    geoms, heights = [], []
    with gzip.open(local, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                feat = json.loads(line)
            except json.JSONDecodeError:
                continue
            g = feat.get("geometry")
            if not g:
                continue
            try:
                geoms.append(shape(g))
            except Exception:
                continue
            h = (feat.get("properties") or {}).get("height")
            heights.append(float(h) if h is not None and h > 0 else None)
    gdf = gpd.GeoDataFrame({"height": heights, "geometry": geoms}, crs="EPSG:4326")
    return gdf.dropna(subset=["geometry"])


def load_ms_footprints_bbox(
    min_lat: float, min_lon: float, max_lat: float, max_lon: float,
    dst_crs=None,
) -> gpd.GeoDataFrame:
    """Return MS building footprints (with heights) covering a bbox.

    Empty GeoDataFrame is returned when the network is unreachable or
    Microsoft has no coverage for the requested tiles."""
    bbox_poly = box(min_lon, min_lat, max_lon, max_lat)
    keys = quadkeys_for_bbox(min_lat, min_lon, max_lat, max_lon)

    try:
        matches = _urls_for_quadkeys(keys)
    except Exception:
        return gpd.GeoDataFrame(geometry=[], crs=dst_crs or "EPSG:4326")

    if matches.empty:
        return gpd.GeoDataFrame(geometry=[], crs=dst_crs or "EPSG:4326")

    frames = []
    for _, row in matches.iterrows():
        url = row["Url"]
        local = MS_CACHE / f"{row['Location']}_{row['QuadKey']}.csv.gz"
        if not local.exists():
            try:
                r = requests.get(url, timeout=60, stream=True)
                r.raise_for_status()
                local.write_bytes(r.content)
            except Exception:
                continue
        try:
            tile = _decode_tile(local)
        except Exception:
            continue
        # Clip to bbox to keep it small.
        clipped = tile[tile.intersects(bbox_poly)]
        frames.append(clipped)

    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=dst_crs or "EPSG:4326")
    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    return combined.to_crs(dst_crs) if dst_crs is not None else combined


def add_missing_buildings_from_ms(
    osm_buildings: gpd.GeoDataFrame,
    ms_buildings: gpd.GeoDataFrame,
    default_height_m: float = 15.0,
) -> gpd.GeoDataFrame:
    """Extend the OSM footprints layer with MS footprints that OSM lacks.

    For every MS building whose polygon does *not* overlap any OSM building,
    we append it with `default_height_m` (MS has no reliable heights for
    India / most of South Asia; 15 m ~= a 5-storey placeholder).

    Returns a NEW GeoDataFrame; does not mutate inputs.
    """
    if len(ms_buildings) == 0:
        return osm_buildings.copy()

    ms = ms_buildings.to_crs(osm_buildings.crs)[["geometry"]].copy()

    if len(osm_buildings) == 0:
        # Nothing to spatial-join against — all MS rows are "missing".
        ms["height"] = default_height_m
        return gpd.GeoDataFrame(
            pd.concat([osm_buildings, ms[["height", "geometry"]]], ignore_index=True),
            crs=osm_buildings.crs,
        )

    # Spatially join MS → OSM; any MS row with no OSM match is missing.
    joined = gpd.sjoin(ms, osm_buildings[["geometry"]], how="left", predicate="intersects")
    missing_mask = joined["index_right"].isna()
    missing = joined[missing_mask].drop(columns=["index_right"]).drop_duplicates(subset="geometry")
    if len(missing) == 0:
        return osm_buildings.copy()

    missing = missing[["geometry"]].copy()
    missing["height"] = default_height_m
    combined = gpd.GeoDataFrame(
        pd.concat([osm_buildings, missing[["height", "geometry"]]], ignore_index=True),
        crs=osm_buildings.crs,
    )
    return combined


def merge_heights_from_ms(
    osm_buildings: gpd.GeoDataFrame,
    ms_buildings: gpd.GeoDataFrame,
    default_min_h: float = 4.0,
) -> gpd.GeoDataFrame:
    """Overlay MS heights on OSM footprints.

    For each OSM building whose current `height` looks like the fallback
    default (i.e. no real OSM signal), find the largest-overlap MS footprint
    within its polygon and adopt that height when it's larger than the OSM
    guess. Returns a copy — does not mutate `osm_buildings`.
    """
    if len(ms_buildings) == 0:
        return osm_buildings.copy()

    ms = ms_buildings.to_crs(osm_buildings.crs)
    ms_valid = ms[ms["height"].notna() & (ms["height"] > default_min_h)]
    if ms_valid.empty:
        return osm_buildings.copy()

    joined = gpd.sjoin(osm_buildings, ms_valid[["height", "geometry"]],
                       how="left", predicate="intersects",
                       lsuffix="osm", rsuffix="ms")
    # Take the max MS height per OSM building (multiple MS tiles may overlap).
    grouped = joined.groupby(joined.index)["height_ms"].max()

    out = osm_buildings.copy()
    replacement = grouped.reindex(out.index)
    # Adopt MS heights wherever OSM was using the default (10–15 m).
    use_ms = replacement.notna() & (replacement > out["height"])
    out.loc[use_ms, "height"] = replacement[use_ms]
    return out
