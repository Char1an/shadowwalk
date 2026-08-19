import json

import pandas as pd
import pytest

from src.weather import WeatherConditions, _parse, fetch_conditions


def test_heat_multiplier_baseline_is_one():
    w = WeatherConditions(temp_c=25, uv_index=5, shortwave_w_m2=500,
                          when=pd.Timestamp("2026-05-15 12:00", tz="UTC"))
    assert w.heat_multiplier() == pytest.approx(1.0, abs=1e-6)


def test_heat_multiplier_scales_up_on_hot_day():
    w = WeatherConditions(temp_c=42, uv_index=11, shortwave_w_m2=900,
                          when=pd.Timestamp("2026-06-21 15:00", tz="UTC"))
    # ~3.4 + 2.0 + 1.6 = ~1 + 7 = 8; should be well above the baseline of 1
    assert w.heat_multiplier() > 4.0


def test_offline_fallback(monkeypatch):
    """If Open-Meteo is unreachable, we get sane defaults rather than a crash."""
    def boom(*a, **kw):
        raise ConnectionError("simulated network failure")
    monkeypatch.setattr("src.weather.requests.get", boom)

    w = fetch_conditions(0.0, 0.0, pd.Timestamp("1999-01-01 12:00", tz="UTC"))
    assert 0 < w.temp_c < 60
    assert w.heat_multiplier() > 0


def test_plain_english_scales_with_temperature():
    """The user-facing sentence should upgrade in severity as it heats up."""
    cool = WeatherConditions(temp_c=18, uv_index=2, shortwave_w_m2=200,
                             when=pd.Timestamp("2026-01-01 10:00", tz="UTC"))
    scorching = WeatherConditions(temp_c=44, uv_index=11, shortwave_w_m2=950,
                                  when=pd.Timestamp("2026-06-01 14:00", tz="UTC"))
    assert "comfortable" in cool.plain_english()
    assert "extreme" in scorching.plain_english() or "life-threatening" in scorching.plain_english()
    # UV descriptions
    assert "low" in cool.plain_english()
    assert "extreme" in scorching.plain_english()


def test_parse_picks_nearest_hour():
    data = {
        "hourly": {
            "time":               ["2026-05-15T13:00", "2026-05-15T14:00", "2026-05-15T15:00"],
            "temperature_2m":     [30.0, 33.0, 36.0],
            "uv_index":           [6.0, 8.0, 9.0],
            "shortwave_radiation": [600.0, 700.0, 800.0],
        }
    }
    got = _parse(data, pd.Timestamp("2026-05-15 14:20", tz="Asia/Kolkata"))
    assert got.temp_c == 33.0
    assert got.uv_index == 8.0
