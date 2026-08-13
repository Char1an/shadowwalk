import pandas as pd
import pytest

from src.sun import get_sun_position, is_daytime


def test_sun_high_at_local_noon_chennai():
    # Chennai in June, roughly local solar noon → sun should be high.
    when = pd.Timestamp("2026-06-21 12:15", tz="Asia/Kolkata")
    az, elev = get_sun_position(13.0827, 80.2707, when)
    assert 0 <= az <= 360
    assert elev > 60


def test_sun_below_horizon_at_midnight():
    when = pd.Timestamp("2026-06-21 00:00", tz="Asia/Kolkata")
    _, elev = get_sun_position(13.0827, 80.2707, when)
    assert elev < 0
    assert not is_daytime(13.0827, 80.2707, when)


def test_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        get_sun_position(13.0827, 80.2707, pd.Timestamp("2026-06-21 12:00"))
