"""Render each results/hero_*.html to a PNG using headless Chromium.

Requires: pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

RESULTS = Path(__file__).resolve().parents[1] / "results"


def main() -> None:
    htmls = sorted(RESULTS.glob("hero_*.html"))
    if not htmls:
        print("no hero_*.html files found in results/")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for html in htmls:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(f"file://{html.resolve()}")
            # Give Leaflet tiles a beat to load.
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            out = html.with_suffix(".png")
            page.screenshot(path=str(out), full_page=False)
            print(f"✔ {out.relative_to(RESULTS.parent)}")
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
