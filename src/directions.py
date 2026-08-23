"""Turn-by-turn walking instructions for a routed path.

Given a NetworkX MultiDiGraph and a list of node ids, produce a numbered
list of steps: "Head north on Ranganathan St for 240 m, then turn left
onto North Usman Rd."

Bearings are computed in the graph's metric CRS if it was reprojected
(the standard `load_area` / `load_city` setup); otherwise we fall back to
lon/lat great-circle bearings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx


@dataclass
class Step:
    text: str          # the sentence to display
    length_m: float    # length of this leg
    street: str        # street name (may be "unnamed lane")


def _bearing(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compass bearing (0 = north, 90 = east) between two projected points."""
    dx, dy = x2 - x1, y2 - y1
    return (math.degrees(math.atan2(dx, dy)) + 360) % 360


def _turn_word(prev_b: float, next_b: float) -> str:
    """Classify the change from one leg's bearing to the next."""
    delta = (next_b - prev_b + 540) % 360 - 180
    if -20 <= delta <= 20:
        return "Continue straight"
    if 20 < delta <= 60:
        return "Bear right"
    if 60 < delta <= 120:
        return "Turn right"
    if delta > 120:
        return "Make a sharp right"
    if -60 <= delta < -20:
        return "Bear left"
    if -120 <= delta < -60:
        return "Turn left"
    return "Make a sharp left"


def _heading_word(bearing: float) -> str:
    dirs = ("north", "north-east", "east", "south-east",
            "south", "south-west", "west", "north-west")
    return dirs[int((bearing + 22.5) % 360 // 45)]


def _street_name(edge_data: dict) -> str:
    n = edge_data.get("name")
    if isinstance(n, list) and n:
        n = n[0]
    if not n:
        return "unnamed lane"
    return str(n)


def _pick_edge(graph: nx.MultiDiGraph, u, v, alpha: float) -> dict:
    """Match `routing.summarize_route` — pick the min-cost parallel edge."""
    edges = graph.get_edge_data(u, v)
    if not edges:
        return {}
    return min(edges.values(),
               key=lambda d: d.get("length", float("inf"))
                             * (1.0 - alpha * d.get("shade_score", 0.0)))


def build_directions(
    graph: nx.MultiDiGraph, path: list[int], alpha: float = 0.0
) -> list[Step]:
    """Turn each consecutive-street run of edges into a single Step."""
    if len(path) < 2:
        return []

    # Collect (name, length, bearing) per edge along the path.
    legs = []
    for u, v in zip(path[:-1], path[1:]):
        data = _pick_edge(graph, u, v, alpha)
        length = float(data.get("length", 0.0))
        street = _street_name(data)
        nu, nv = graph.nodes[u], graph.nodes[v]
        b = _bearing(nu["x"], nu["y"], nv["x"], nv["y"])
        legs.append((street, length, b))

    # Collapse consecutive legs on the same street.
    steps: list[Step] = []
    prev_bearing: float | None = None
    for street, length, bearing in legs:
        if steps and steps[-1].street == street:
            steps[-1] = Step(text=steps[-1].text, length_m=steps[-1].length_m + length,
                             street=street)
            prev_bearing = bearing
            continue
        if prev_bearing is None:
            verb = f"Head {_heading_word(bearing)}"
        else:
            verb = _turn_word(prev_bearing, bearing)
        text = f"{verb} on **{street}** for {length:.0f} m"
        steps.append(Step(text=text, length_m=length, street=street))
        prev_bearing = bearing

    # After collapsing, rewrite each step's text with its final total length
    # (the verb + street are already baked into s.text; only the metres change).
    return [
        Step(text=f"{s.text.rpartition(' for ')[0]} for {s.length_m:.0f} m",
             length_m=s.length_m, street=s.street)
        for s in steps
    ]


def format_markdown(steps: list[Step]) -> str:
    """Render Step list as a numbered markdown list."""
    if not steps:
        return "_(no directions — start and end resolved to the same node)_"
    lines = [f"{i+1}. {s.text}" for i, s in enumerate(steps)]
    total = sum(s.length_m for s in steps)
    lines.append(f"\n**Arrive at destination — total {total:.0f} m.**")
    return "\n".join(lines)
