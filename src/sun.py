"""Sun position via pvlib."""
from __future__ import annotations

import pandas as pd
import pvlib


def get_sun_position(lat: float, lon: float, when: pd.Timestamp) -> tuple[float, float]:
    """Return (azimuth_deg, elevation_deg) for a location and time.

    Azimuth is measured clockwise from North (pvlib convention).
    Elevation is the apparent (refraction-corrected) angle above the horizon;
    negative values mean the sun is below the horizon.

    `when` must be timezone-aware.
    """
    if when.tzinfo is None:
        raise ValueError("`when` must be timezone-aware (use pd.Timestamp(..., tz=...))")
    idx = pd.DatetimeIndex([when])
    sp = pvlib.solarposition.get_solarposition(idx, lat, lon)
    return float(sp["azimuth"].iloc[0]), float(sp["apparent_elevation"].iloc[0])


def is_daytime(lat: float, lon: float, when: pd.Timestamp, min_elevation: float = 1.0) -> bool:
    """True when the sun is meaningfully above the horizon."""
    _, elev = get_sun_position(lat, lon, when)
    return elev >= min_elevation
