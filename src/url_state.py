"""Sync the app's picked state to and from URL query parameters.

Makes routes shareable: e.g.
    https://…/?city=delhi&hour=9&preset=cool&start=28.6345,77.214&end=28.6285,77.22

Reading happens once at the top of the run (before widgets); writing happens
at the very end so the URL reflects the final state.
"""
from __future__ import annotations

import streamlit as st

_PRESET_TO_ALPHA = {"fast": 0.0, "balanced": 0.6, "cool": 0.9}
_ALPHA_TO_PRESET = {v: k for k, v in _PRESET_TO_ALPHA.items()}
_PRESET_TO_LABEL = {
    "fast":     "Fastest walk (no detour)",
    "balanced": "Balanced (small detour OK)",
    "cool":     "Coolest walk (bigger detour OK)",
}
_LABEL_TO_PRESET = {v: k for k, v in _PRESET_TO_LABEL.items()}


def _parse_latlon(raw: str) -> tuple[float, float] | None:
    try:
        a, b = raw.split(",")
        return float(a), float(b)
    except (ValueError, AttributeError):
        return None


def read_from_url(known_cities: list[str]) -> None:
    """Populate st.session_state from the URL, if this is the first render.

    Called once, immediately after `st.set_page_config`, before any widget
    key is instantiated — otherwise we'd hit Streamlit's post-instantiation
    write ban.
    """
    if st.session_state.get("_url_read"):
        return
    st.session_state["_url_read"] = True

    qp = st.query_params

    city = qp.get("city")
    if city in known_cities:
        st.session_state["city_selectbox"] = city

    try:
        hour = float(qp.get("hour", ""))
        if 5.0 <= hour <= 20.0:
            st.session_state["hour_slider"] = round(hour * 2) / 2
    except (TypeError, ValueError):
        pass

    preset = qp.get("preset")
    if preset in _PRESET_TO_LABEL:
        st.session_state["preset_radio"] = _PRESET_TO_LABEL[preset]

    start = _parse_latlon(qp.get("start", ""))
    if start:
        st.session_state["start"] = start
    end = _parse_latlon(qp.get("end", ""))
    if end:
        st.session_state["end"] = end


def write_to_url(
    city_key: str, hour_float: float, alpha: float,
    start: tuple[float, float] | None, end: tuple[float, float] | None,
) -> None:
    """Reflect the current UI state back into the URL query string."""
    qp = st.query_params
    qp["city"] = city_key
    qp["hour"] = f"{hour_float:.1f}"
    qp["preset"] = _ALPHA_TO_PRESET.get(alpha, "balanced")
    if start:
        qp["start"] = f"{start[0]:.5f},{start[1]:.5f}"
    else:
        qp.pop("start", None)
    if end:
        qp["end"] = f"{end[0]:.5f},{end[1]:.5f}"
    else:
        qp.pop("end", None)
