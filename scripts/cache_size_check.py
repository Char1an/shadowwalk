"""Estimate RAM footprint per city — Streamlit Community Cloud caps at 1 GB."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CITIES
from src.data_loader import load_area


AREAS = [
    ("chennai",   13.0418, 80.2341, 800),
    ("delhi",     28.6315, 77.2167, 800),
    ("ahmedabad", 23.0245, 72.5866, 800),
]


def sizeof_mb(obj) -> float:
    return len(pickle.dumps(obj)) / (1024 * 1024)


rows = []
for name, lat, lon, radius in AREAS:
    graph, buildings = load_area(lat, lon, radius)
    g_mb = sizeof_mb(graph)
    b_mb = buildings.memory_usage(deep=True).sum() / (1024 * 1024)
    rows.append({
        "city": name,
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "buildings": len(buildings),
        "graph_MB": round(g_mb, 1),
        "buildings_MB": round(b_mb, 1),
        "total_MB": round(g_mb + b_mb, 1),
    })

df = pd.DataFrame(rows).set_index("city")
print(df.to_string())
print(f"\nΣ all 3 cities: {df['total_MB'].sum():.1f} MB (of 1024 MB Streamlit Cloud cap)")
