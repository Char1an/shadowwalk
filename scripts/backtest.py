"""End-to-end backtest: routing quality per city, α, and w/ vs w/o tree cover."""
from __future__ import annotations

import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_loader import load_area
from src.metrics import summarize_route
from src.routing import shortest_path
from src.shade import compute_edge_shade
from src.sun import get_sun_position
from src.trees import load_tree_cover_area


@dataclass
class Scenario:
    label: str
    lat: float
    lon: float
    radius_m: int
    when: pd.Timestamp


SCENARIOS = [
    # Chennai T. Nagar — coastal humid, morning + midday
    Scenario("Chennai T. Nagar, 08:00", 13.0418, 80.2341, 800,
             pd.Timestamp("2026-05-15 08:00", tz="Asia/Kolkata")),
    Scenario("Chennai T. Nagar, 14:00", 13.0418, 80.2341, 800,
             pd.Timestamp("2026-05-15 14:00", tz="Asia/Kolkata")),
    # Delhi Connaught Place — northern dry-heat, morning + afternoon
    Scenario("Delhi Connaught Place, 09:00", 28.6315, 77.2167, 800,
             pd.Timestamp("2026-05-15 09:00", tz="Asia/Kolkata")),
    Scenario("Delhi Connaught Place, 15:00", 28.6315, 77.2167, 800,
             pd.Timestamp("2026-05-15 15:00", tz="Asia/Kolkata")),
    # Ahmedabad Ashram Road — modern commercial spine with mid-rise offices
    Scenario("Ahmedabad Ashram Road, 17:00", 23.0330, 72.5680, 800,
             pd.Timestamp("2026-05-15 17:00", tz="Asia/Kolkata")),
]
ALPHAS = (0.3, 0.6, 0.9)
N_PAIRS = 15
MIN_PAIR_DIST_M = 400


def _pick_pairs(graph: nx.MultiDiGraph, n: int, seed: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    nodes = list(graph.nodes())
    pairs: list[tuple[int, int]] = []
    tries = 0
    while len(pairs) < n and tries < n * 30:
        tries += 1
        s, t = rng.sample(nodes, 2)
        xu, yu = graph.nodes[s]["x"], graph.nodes[s]["y"]
        xv, yv = graph.nodes[t]["x"], graph.nodes[t]["y"]
        if ((xu - xv) ** 2 + (yu - yv) ** 2) ** 0.5 < MIN_PAIR_DIST_M:
            continue
        pairs.append((s, t))
    return pairs


def _bench(graph, pairs) -> None:
    baselines = []
    for s, t in pairs:
        try:
            baselines.append(summarize_route(graph, shortest_path(graph, s, t, alpha=0.0), alpha=0.0))
        except nx.NetworkXNoPath:
            baselines.append(None)

    header = f"    {'α':>4}  {'Δdist% mean':>12} {'Δdist% p90':>11}  {'Δshade pp':>10}  {'wins':>7}"
    print(header)
    print("    " + "-" * (len(header) - 4))
    for alpha in ALPHAS:
        ddist, dshade, wins, n = [], [], 0, 0
        for (s, t), base in zip(pairs, baselines):
            if base is None:
                continue
            try:
                summ = summarize_route(graph, shortest_path(graph, s, t, alpha=alpha), alpha=alpha)
            except nx.NetworkXNoPath:
                continue
            n += 1
            ddist.append(100 * (summ.distance_m - base.distance_m) / max(base.distance_m, 1e-6))
            dshade.append(100 * (summ.shaded_fraction - base.shaded_fraction))
            if summ.shaded_fraction > base.shaded_fraction + 0.02:
                wins += 1
        p90 = sorted(ddist)[int(0.9 * (len(ddist) - 1))] if ddist else 0.0
        print(f"    {alpha:>4.1f}  {statistics.mean(ddist):>+11.1f}% {p90:>+10.1f}%  "
              f"{statistics.mean(dshade):>+9.1f}   {wins:>3}/{n:>3}")


def run_scenario(sc: Scenario) -> None:
    print(f"\n===== {sc.label} =====")
    t0 = time.perf_counter()
    graph, buildings = load_area(sc.lat, sc.lon, sc.radius_m)
    print(f"  graph {graph.number_of_nodes()}n/{graph.number_of_edges()}e  "
          f"buildings {len(buildings)}  ({time.perf_counter() - t0:.1f}s)")

    trees = load_tree_cover_area(sc.lat, sc.lon, sc.radius_m, dst_crs=buildings.crs)
    print(f"  tree cover polys: {len(trees)}")

    az, elev = get_sun_position(sc.lat, sc.lon, sc.when)
    print(f"  sun az={az:.1f}° elev={elev:.1f}°")

    pairs = _pick_pairs(graph, N_PAIRS, seed=42)

    for label, use_trees in [("buildings only", False), ("buildings + trees", True)]:
        compute_edge_shade(
            graph, buildings, sun_azimuth_deg=az, sun_elevation_deg=elev,
            tree_cover=trees if use_trees else None,
        )
        vals = [d.get("shade_score", 0.0) for _, _, d in graph.edges(data=True)]
        print(f"\n  [{label}]  mean shade={statistics.mean(vals):.2f}  "
              f"frac>0.5={sum(1 for v in vals if v > 0.5)/len(vals):.1%}")
        _bench(graph, pairs)


def main() -> None:
    for sc in SCENARIOS:
        try:
            run_scenario(sc)
        except Exception as e:
            print(f"\n[{sc.label}] failed: {e}")


if __name__ == "__main__":
    main()
