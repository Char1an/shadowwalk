"""Compare shade signal with vs without Microsoft Global Building Footprints."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_loader import load_area
from src.shade import compute_edge_shade
from src.sun import get_sun_position
from src.trees import load_tree_cover_area


LAT, LON, RADIUS = 13.0418, 80.2341, 800
WHEN = pd.Timestamp("2026-05-15 14:00", tz="Asia/Kolkata")


def summarize(label: str, graph):
    vals = [d.get("shade_score", 0.0) for _, _, d in graph.edges(data=True)]
    print(f"{label:>20s}  mean={statistics.mean(vals):.3f}  "
          f"frac>0.5={sum(1 for v in vals if v > 0.5)/len(vals):.1%}")


def main() -> None:
    print(f"→ area: ({LAT}, {LON}) r={RADIUS}m at {WHEN.isoformat()}\n")

    t0 = time.perf_counter()
    graph, buildings = load_area(LAT, LON, RADIUS)
    trees = load_tree_cover_area(LAT, LON, RADIUS, dst_crs=buildings.crs)
    print(f"OSM only: {len(buildings)} buildings, "
          f"height mean={buildings['height'].mean():.1f}m "
          f"({time.perf_counter()-t0:.1f}s)")

    t0 = time.perf_counter()
    try:
        graph_ms, buildings_ms = load_area(LAT, LON, RADIUS, use_ms_footprints=True)
        print(f"OSM+MS  : {len(buildings_ms)} buildings, "
              f"height mean={buildings_ms['height'].mean():.1f}m, "
              f"max={buildings_ms['height'].max():.1f}m "
              f"({time.perf_counter()-t0:.1f}s)")
    except Exception as e:
        print(f"MS footprints unavailable: {e}")
        return

    az, elev = get_sun_position(LAT, LON, WHEN)
    print(f"\nsun az={az:.1f}° elev={elev:.1f}°\n")

    compute_edge_shade(graph,    buildings,    az, elev, tree_cover=trees)
    compute_edge_shade(graph_ms, buildings_ms, az, elev, tree_cover=trees)

    summarize("OSM only", graph)
    summarize("OSM + MS", graph_ms)


if __name__ == "__main__":
    main()
