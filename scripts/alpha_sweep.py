"""α sweep: for each city, plot the detour-cost vs shade-gain trade-off curve.

Runs α ∈ [0.0, 1.0] in 11 steps on a set of random O/D pairs per city, then
saves one matplotlib figure showing all three cities together. The figure
lands in results/ and is embedded in the README.
"""
from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_loader import load_area
from src.metrics import summarize_route
from src.routing import shortest_path
from src.shade import compute_edge_shade
from src.sun import get_sun_position
from src.trees import load_tree_cover_area


SCENARIOS = [
    ("Chennai T. Nagar, 08:00",     13.0418, 80.2341, 800,
     pd.Timestamp("2026-05-15 08:00", tz="Asia/Kolkata")),
    ("Delhi Connaught Place, 09:00", 28.6315, 77.2167, 800,
     pd.Timestamp("2026-05-15 09:00", tz="Asia/Kolkata")),
    ("Ahmedabad Ashram Road, 17:00", 23.0330, 72.5680, 800,
     pd.Timestamp("2026-05-15 17:00", tz="Asia/Kolkata")),
]
ALPHAS = np.linspace(0.0, 1.0, 11)
N_PAIRS = 20
MIN_PAIR_DIST_M = 400
OUT = Path(__file__).resolve().parents[1] / "results" / "alpha_sweep.png"
TABLE_OUT = Path(__file__).resolve().parents[1] / "results" / "compare_cities.md"


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


def sweep(graph, pairs):
    """Return dict {alpha: (mean_detour_pct, mean_shade_pp_gain, mean_sun_min_saved)}."""
    # Baseline = shortest path for each pair (α=0)
    baselines = []
    for s, t in pairs:
        try:
            baselines.append(summarize_route(graph, shortest_path(graph, s, t, alpha=0.0), alpha=0.0))
        except nx.NetworkXNoPath:
            baselines.append(None)

    out = {}
    for alpha in ALPHAS:
        ddists, dshades, savings = [], [], []
        for (s, t), base in zip(pairs, baselines):
            if base is None:
                continue
            try:
                summ = summarize_route(graph, shortest_path(graph, s, t, alpha=alpha), alpha=alpha)
            except nx.NetworkXNoPath:
                continue
            ddists.append(100 * (summ.distance_m - base.distance_m) / max(base.distance_m, 1e-6))
            dshades.append(100 * (summ.shaded_fraction - base.shaded_fraction))
            savings.append(base.sun_exposure_min - summ.sun_exposure_min)
        out[float(alpha)] = (statistics.mean(ddists), statistics.mean(dshades),
                             statistics.mean(savings))
    return out


def main():
    fig, ax = plt.subplots(figsize=(8, 5.5), dpi=120)
    plt.style.use("dark_background")
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#181d29")

    palette = ["#2e86ab", "#e6b800", "#d1495b"]
    all_results = []

    for (label, lat, lon, radius, when), color in zip(SCENARIOS, palette):
        print(f"\n=== {label} ===")
        graph, buildings = load_area(lat, lon, radius)
        trees = load_tree_cover_area(lat, lon, radius, dst_crs=buildings.crs)
        az, elev = get_sun_position(lat, lon, when)
        compute_edge_shade(graph, buildings, az, elev, tree_cover=trees)
        print(f"  graph {graph.number_of_nodes()}n/{graph.number_of_edges()}e  "
              f"sun az={az:.1f}° elev={elev:.1f}°")

        pairs = _pick_pairs(graph, N_PAIRS, seed=42)
        results = sweep(graph, pairs)

        dd = [results[a][0] for a in ALPHAS]
        ds = [results[a][1] for a in ALPHAS]
        ax.plot(dd, ds, "-o", color=color, label=label.split(",")[0],
                markersize=5, linewidth=1.8)
        # Annotate α values along the curve (indices, not values, avoids float lookup)
        for target in (0.3, 0.6, 0.9):
            i = int(round(target * (len(ALPHAS) - 1)))
            ax.annotate(f"α={ALPHAS[i]:.1f}", (dd[i], ds[i]),
                        color=color, fontsize=8, alpha=0.85,
                        xytext=(4, 3), textcoords="offset points")

        # Grab headline numbers for the compare table (α closest to 0.9)
        det, sha, sav = results[float(ALPHAS[-2])]  # α=0.9 in an 11-step 0..1 sweep
        all_results.append((label, det, sha, sav))

    ax.set_xlabel("Extra distance vs shortest (%)", color="#eee")
    ax.set_ylabel("Extra shade vs shortest (percentage points)", color="#eee")
    ax.set_title("ShadowWalk α sweep — shade gain vs detour cost", color="#fff", pad=14)
    ax.grid(True, alpha=0.15)
    ax.legend(facecolor="#222", edgecolor="#444", labelcolor="#eee")
    fig.tight_layout()
    OUT.parent.mkdir(exist_ok=True)
    fig.savefig(OUT, facecolor=fig.get_facecolor())
    print(f"\n✔ {OUT}")

    # --- compare-cities markdown table --------------------------------
    lines = [
        "# ShadowWalk — headline numbers (α = 0.9, 20 random O/D pairs each)",
        "",
        "| Scenario | Mean detour | Mean extra shade | Mean sun exposure saved |",
        "|---|---:|---:|---:|",
    ]
    for label, det, sha, sav in all_results:
        lines.append(f"| {label} | {det:+.1f}% | {sha:+.1f} pp | {sav:.1f} min |")
    TABLE_OUT.write_text("\n".join(lines) + "\n")
    print(f"✔ {TABLE_OUT}")


if __name__ == "__main__":
    main()
