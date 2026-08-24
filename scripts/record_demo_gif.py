"""Sweep the hour of day for one scene and record a GIF of the routes morphing.

For each hour step, we:
  1. recompute the shadow layer at that sun angle
  2. recompute both the shortest and the shade routes
  3. render a folium map (routes + shadow overlay)
  4. save it as HTML then screenshot to PNG with headless Chromium

Finally stitch all the PNG frames into an animated GIF.

Requires: playwright (with chromium installed), imageio, PIL.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

import folium
import imageio.v3 as iio
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import CITIES
from src.data_loader import load_area
from src.metrics import summarize_route
from src.routing import route_between
from src.shade import compute_edge_shade
from src.sun import get_sun_position
from src.trees import load_tree_cover_area
from src.viz import render_routes


# ─── scene ────────────────────────────────────────────────────────────
SCENE = dict(
    name="chennai_hour_sweep",
    city="chennai",
    lat=13.0418, lon=80.2341, radius=800,
    start=(13.0440, 80.2320),
    end=(13.0395, 80.2370),
    alpha=0.9,
    date="2026-05-15",
)
HOURS = [round(h, 1) for h in list(pd.Series(range(12, 37)) / 2)]  # 6.0, 6.5, … 18.0
FRAME_SIZE = (1200, 800)
GIF_MS_PER_FRAME = 220
OUT = Path(__file__).resolve().parents[1] / "results" / f"demo_{SCENE['name']}.gif"


def _add_caption(img_path: Path, hour_str: str, metrics_str: str) -> None:
    """Burn the hour label + metrics onto a PNG in-place."""
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 34)
        small_font = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 20)
    except OSError:
        title_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    # Semi-opaque banner strip
    bar = Image.new("RGBA", (img.width, 90), (16, 20, 28, 200))
    img.paste(bar, (0, 0), bar)
    draw.text((22, 12), f"ShadowWalk — Chennai T. Nagar  ·  {hour_str}",
              fill=(250, 250, 250), font=title_font)
    draw.text((22, 55), metrics_str, fill=(180, 200, 220), font=small_font)
    img.save(img_path)


def main() -> None:
    city = CITIES[SCENE["city"]]
    print(f"→ loading {city.query}")
    graph, buildings = load_area(SCENE["lat"], SCENE["lon"], SCENE["radius"])
    trees = load_tree_cover_area(SCENE["lat"], SCENE["lon"], SCENE["radius"],
                                 dst_crs=buildings.crs)
    print(f"  graph {graph.number_of_nodes()}n/{graph.number_of_edges()}e, "
          f"{len(buildings)} buildings, {len(trees)} tree polys")

    tmpdir = Path(tempfile.mkdtemp(prefix="shadowwalk_frames_"))
    print(f"→ frames dir: {tmpdir}")

    frames: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": FRAME_SIZE[0], "height": FRAME_SIZE[1]})

        for i, h in enumerate(HOURS):
            hh, mm = int(h), int((h - int(h)) * 60)
            when = pd.Timestamp(f"{SCENE['date']} {hh:02d}:{mm:02d}", tz=city.tz)
            az, elev = get_sun_position(SCENE["lat"], SCENE["lon"], when)

            if elev <= 0:
                # Skip night — shadow layer would be uniformly "everywhere shaded"
                # which makes the frame useless.
                print(f"  hour {h:.1f}h — sun below horizon, skipped")
                continue

            compute_edge_shade(graph, buildings, az, elev, tree_cover=trees)
            try:
                short = route_between(graph, *SCENE["start"], *SCENE["end"], alpha=0.0)
                shade = route_between(graph, *SCENE["start"], *SCENE["end"], alpha=SCENE["alpha"])
            except Exception as e:
                print(f"  hour {h:.1f}h — routing failed: {e}")
                continue

            a = summarize_route(graph, short, alpha=0.0)
            b = summarize_route(graph, shade, alpha=SCENE["alpha"])

            fmap = render_routes(graph, short, shade,
                                 shadow_layer=graph.graph.get("shadow_layer"))
            html_path = tmpdir / f"frame_{i:03d}.html"
            png_path  = tmpdir / f"frame_{i:03d}.png"
            fmap.save(str(html_path))

            page.goto(f"file://{html_path.resolve()}")
            page.wait_for_load_state("networkidle")
            time.sleep(0.5)  # give Leaflet tiles a beat
            page.screenshot(path=str(png_path), full_page=False)

            hour_str = f"{hh:02d}:{mm:02d}  ·  sun elev {elev:.0f}°"
            metrics = (f"Shortest: {a.distance_m:.0f} m, {100*a.shaded_fraction:.0f}% shaded, "
                       f"{a.sun_exposure_min:.1f} min sun   →   "
                       f"ShadowWalk: {b.distance_m:.0f} m, {100*b.shaded_fraction:.0f}% shaded, "
                       f"{b.sun_exposure_min:.1f} min sun")
            _add_caption(png_path, hour_str, metrics)
            frames.append(png_path)
            print(f"  hour {h:.1f}h — az {az:.0f}° elev {elev:.0f}° · "
                  f"shortest {100*a.shaded_fraction:.0f}% shaded · "
                  f"shade {100*b.shaded_fraction:.0f}% shaded")

        browser.close()

    if not frames:
        print("no frames captured")
        return

    print(f"→ stitching {len(frames)} frames into {OUT}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images = [np.array(Image.open(f)) for f in frames]
    # Duration in seconds per frame for imageio v3
    iio.imwrite(OUT, images, duration=GIF_MS_PER_FRAME / 1000, loop=0)
    print(f"✔ {OUT}  ({OUT.stat().st_size / 1024:.0f} KB)")

    shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
