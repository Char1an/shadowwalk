"""Route summary metrics: distance, shade %, sun-exposure minutes."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .config import WALK_SPEED_MPS


@dataclass
class RouteSummary:
    distance_m: float
    shaded_fraction: float       # length-weighted 0..1
    walk_time_min: float
    sun_exposure_min: float
    felt_heat_min: float | None = None  # sun_exposure × weather multiplier

    def as_dict(self) -> dict:
        d = {
            "distance_m": round(self.distance_m, 1),
            "shaded_pct": round(100 * self.shaded_fraction, 1),
            "walk_time_min": round(self.walk_time_min, 1),
            "sun_exposure_min": round(self.sun_exposure_min, 1),
        }
        if self.felt_heat_min is not None:
            d["felt_heat_min"] = round(self.felt_heat_min, 1)
        return d

    def apply_weather(self, multiplier: float) -> "RouteSummary":
        """Return a copy with `felt_heat_min` filled in from a weather multiplier."""
        return RouteSummary(
            self.distance_m, self.shaded_fraction, self.walk_time_min,
            self.sun_exposure_min, felt_heat_min=self.sun_exposure_min * multiplier,
        )


def summarize_route(
    graph: nx.MultiDiGraph, path: list[int], alpha: float = 0.0
) -> RouteSummary:
    """Compute length-weighted summary metrics for a path (sequence of node ids).

    `alpha` should match the value the router used — for `MultiDiGraph`s with
    parallel edges, this ensures we pick the *same* edge the router did
    (`length × (1 − α × shade_score)` minimum), not merely the shortest.
    """
    def _cost(d: dict) -> float:
        return d.get("length", float("inf")) * (1.0 - alpha * d.get("shade_score", 0.0))

    total_len = 0.0
    weighted_shade = 0.0
    for u, v in zip(path[:-1], path[1:]):
        edges = graph.get_edge_data(u, v)
        if not edges:
            continue
        data = min(edges.values(), key=_cost)
        length = data.get("length", 0.0)
        shade = data.get("shade_score", 0.0)
        total_len += length
        weighted_shade += length * shade

    frac = (weighted_shade / total_len) if total_len > 0 else 0.0
    walk_time_min = (total_len / WALK_SPEED_MPS) / 60.0
    sun_exposure_min = walk_time_min * (1 - frac)
    return RouteSummary(total_len, frac, walk_time_min, sun_exposure_min)
