"""Address → (lat, lon) via OSM Nominatim.

Free, no API key, but rate-limited: 1 req/s per IP and a mandatory
User-Agent header. We disk-cache each query so repeated searches for the
same string never hit the server twice.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

from .config import DATA_DIR

CACHE = DATA_DIR / "geocode"
CACHE.mkdir(parents=True, exist_ok=True)

USER_AGENT = "ShadowWalk/0.1 (github.com/Char1an/shadowwalk — shade-aware pedestrian routing)"


def _cache_path(query: str, viewbox: str | None) -> Path:
    key = hashlib.sha1(f"{query}|{viewbox or ''}".encode("utf-8")).hexdigest()[:16]
    return CACHE / f"{key}.json"


def geocode(
    query: str,
    viewbox: tuple[float, float, float, float] | None = None,
    limit: int = 3,
) -> list[dict]:
    """Search Nominatim for a place name.

    Returns up to `limit` matches, each `{display_name, lat, lon}`. Empty
    list on total failure — never raises, so the UI can degrade gracefully.

    `viewbox` biases results toward a bounding box (min_lon, min_lat,
    max_lon, max_lat) — helpful for "MG Road" which exists in several
    Indian cities.
    """
    query = query.strip()
    if not query:
        return []

    vb_key = None
    if viewbox is not None:
        vb_key = ",".join(f"{v:.4f}" for v in viewbox)

    cache_file = _cache_path(query, vb_key)
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass

    params = {
        "q": query,
        "format": "json",
        "limit": limit,
        "addressdetails": 0,
    }
    if viewbox is not None:
        params["viewbox"] = vb_key
        params["bounded"] = 1

    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=8,
        )
        r.raise_for_status()
        raw = r.json()
    except Exception:
        return []

    results = [
        {
            "display_name": item["display_name"],
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
        }
        for item in raw
    ]
    try:
        cache_file.write_text(json.dumps(results))
    except OSError:
        pass
    return results
