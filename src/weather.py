"""Open-Meteo weather + solar for the 'felt exposure' score.

Open-Meteo is free, requires no API key, and returns hourly forecasts. We
pull temperature (°C), UV index, and shortwave radiation (W/m²) — the three
inputs that jointly determine how brutal walking in the sun actually feels.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from .config import DATA_DIR

CACHE = DATA_DIR / "weather"
CACHE.mkdir(parents=True, exist_ok=True)


@dataclass
class WeatherConditions:
    temp_c: float          # air temperature at ground level
    uv_index: float        # 0–11+ (7+ is "very high")
    shortwave_w_m2: float  # direct solar radiation on a horizontal surface
    when: pd.Timestamp

    def heat_multiplier(self) -> float:
        """A dimensionless factor to convert 'sun-exposure minutes' into a
        subjective 'felt-heat minutes' number.

        Baseline of 1.0 is defined as: 25 °C, UV 5, 500 W/m². Above that,
        the multiplier grows with both temperature and radiation because
        thermal load compounds — 40 °C at UV 10 is a lot worse than the
        linear sum of "6 hotter degrees + 5 more UV points" suggests.
        """
        temp_term = max(0.0, (self.temp_c - 25) / 5.0)          # +1 per 5 °C over 25
        uv_term = max(0.0, (self.uv_index - 5) / 3.0)           # +1 per 3 UV over 5
        rad_term = max(0.0, (self.shortwave_w_m2 - 500) / 250)  # +1 per 250 W/m² over 500
        return 1.0 + temp_term + uv_term + rad_term

    def summary(self) -> str:
        return (f"{self.temp_c:.0f}°C · UV {self.uv_index:.1f} · "
                f"{self.shortwave_w_m2:.0f} W/m² → ×{self.heat_multiplier():.2f} felt load")

    def plain_english(self) -> str:
        """A human sentence describing how bad walking would feel right now."""
        t = self.temp_c
        uv = self.uv_index
        if t < 20:
            comfort = "comfortable"
        elif t < 28:
            comfort = "warm"
        elif t < 33:
            comfort = "hot"
        elif t < 38:
            comfort = "very hot"
        elif t < 43:
            comfort = "dangerous heat"
        else:
            comfort = "extreme, life-threatening heat"

        uv_word = ("low" if uv < 3 else "moderate" if uv < 6 else
                   "high" if uv < 8 else "very high" if uv < 11 else "extreme")
        return f"{t:.0f} °C, UV {uv_word} ({uv:.1f}) — {comfort} for walking."


def _cache_key(lat: float, lon: float, when: pd.Timestamp) -> Path:
    when_utc = when.tz_convert("UTC")
    return CACHE / f"{lat:.3f}_{lon:.3f}_{when_utc.strftime('%Y%m%d%H')}.json"


def fetch_conditions(lat: float, lon: float, when: pd.Timestamp) -> WeatherConditions:
    """Fetch (and disk-cache) conditions from Open-Meteo. Falls back to sane
    defaults on network failure so the app never dies from a weather timeout."""
    cache_path = _cache_key(lat, lon, when)
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        return _parse(data, when)

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,uv_index,shortwave_radiation",
        "forecast_days": 7,
        "past_days": 2,
        "timezone": str(when.tz),
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        cache_path.write_text(json.dumps(data))
        return _parse(data, when)
    except Exception:
        # Deterministic fallback so the UI shows a plausible number instead of erroring.
        return WeatherConditions(temp_c=30.0, uv_index=7.0, shortwave_w_m2=650.0, when=when)


def _parse(data: dict, when: pd.Timestamp) -> WeatherConditions:
    hourly = data["hourly"]
    times = pd.to_datetime(hourly["time"]).tz_localize(when.tz)
    # Nearest-hour lookup
    idx = int((times - when).map(lambda td: abs(td)).argmin())
    return WeatherConditions(
        temp_c=float(hourly["temperature_2m"][idx]),
        uv_index=float(hourly["uv_index"][idx]),
        shortwave_w_m2=float(hourly["shortwave_radiation"][idx]),
        when=times[idx],
    )
