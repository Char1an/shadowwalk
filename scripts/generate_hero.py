"""Generate the 'hero' HTML map for the README.

Renders a Phoenix downtown routing example at 3 PM with the shadow overlay
and both routes, saving to results/hero_phoenix.html — open in a browser to
screenshot for the README.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_loader import load_area
from src.metrics import summarize_route
from src.routing import route_between
from src.shade import compute_edge_shade
from src.sun import get_sun_position
from src.trees import load_tree_cover_area
from src.viz import render_routes


OUT_DIR = Path(__file__).resolve().parents[1] / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)


SCENES = [
    dict(
        # T. Nagar — dense central Chennai retail district.
        name="chennai_8am",
        lat=13.0418, lon=80.2341, radius=800,
        when=pd.Timestamp("2026-05-15 08:00", tz="Asia/Kolkata"),
        start=(13.0440, 80.2320),
        end=(13.0395, 80.2370),
        alpha=0.9,
    ),
    dict(
        # Connaught Place — dense central Delhi.
        name="delhi_9am",
        lat=28.6315, lon=77.2167, radius=800,
        when=pd.Timestamp("2026-05-15 09:00", tz="Asia/Kolkata"),
        start=(28.6345, 77.2140),
        end=(28.6285, 77.2200),
        alpha=0.9,
    ),
    dict(
        # Ashram Road — Ahmedabad's modern commercial spine (better OSM coverage
        # than the old-city pol district; taller buildings + more tree data).
        name="ahmedabad_5pm",
        lat=23.0330, lon=72.5680, radius=800,
        when=pd.Timestamp("2026-05-15 17:00", tz="Asia/Kolkata"),
        start=(23.0360, 72.5660),
        end=(23.0295, 72.5710),
        alpha=0.9,
    ),
]


def run(scene: dict) -> None:
    print(f"\n=== {scene['name']} ===")
    t0 = time.perf_counter()
    graph, buildings = load_area(scene["lat"], scene["lon"], scene["radius"])
    trees = load_tree_cover_area(scene["lat"], scene["lon"], scene["radius"],
                                 dst_crs=buildings.crs)
    print(f"  loaded {graph.number_of_nodes()}n / {graph.number_of_edges()}e / "
          f"{len(buildings)} buildings / {len(trees)} tree polys "
          f"({time.perf_counter()-t0:.1f}s)")

    az, elev = get_sun_position(scene["lat"], scene["lon"], scene["when"])
    print(f"  sun az={az:.1f}° elev={elev:.1f}°")

    compute_edge_shade(graph, buildings, az, elev, tree_cover=trees)

    s_lat, s_lon = scene["start"]
    e_lat, e_lon = scene["end"]
    short = route_between(graph, s_lat, s_lon, e_lat, e_lon, alpha=0.0)
    shade = route_between(graph, s_lat, s_lon, e_lat, e_lon, alpha=scene["alpha"])

    a = summarize_route(graph, short, alpha=0.0)
    b = summarize_route(graph, shade, alpha=scene["alpha"])
    print(f"  shortest  : {a.distance_m:>5.0f} m, {100*a.shaded_fraction:>4.1f}% shaded, {a.sun_exposure_min:>4.1f} min sun")
    print(f"  shade α={scene['alpha']:.1f}: {b.distance_m:>5.0f} m, {100*b.shaded_fraction:>4.1f}% shaded, {b.sun_exposure_min:>4.1f} min sun")
    print(f"  → +{b.distance_m-a.distance_m:.0f} m, +{100*(b.shaded_fraction-a.shaded_fraction):.1f} pp shade, "
          f"−{a.sun_exposure_min-b.sun_exposure_min:.1f} min sun")

    fmap = render_routes(graph, short, shade,
                         shadow_layer=graph.graph.get("shadow_layer"))
    out = OUT_DIR / f"hero_{scene['name']}.html"
    fmap.save(str(out))
    print(f"  ✔ saved {out}")


if __name__ == "__main__":
    for scene in SCENES:
        try:
            run(scene)
        except Exception as e:
            print(f"[{scene['name']}] failed: {e}")
