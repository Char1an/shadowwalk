"""Sanity checks on the city registry."""
import math

from src.config import CITIES


def test_all_cities_have_demo_route_near_centre():
    """The 'Try example route' button drops the demo start/end on the map.
    Both points must fall inside the default 1.5 km search radius so the
    router doesn't snap them to the graph boundary."""
    default_radius_m = 1500

    for key, city in CITIES.items():
        for label, (lat, lon) in [("start", city.demo_start), ("end", city.demo_end)]:
            # Rough metres-per-degree approximations (good enough for a 1.5 km sanity)
            dy = (lat - city.lat) * 111_000
            dx = (lon - city.lon) * 111_000 * math.cos(math.radians(city.lat))
            dist = math.hypot(dx, dy)
            assert dist <= default_radius_m, (
                f"{key} demo_{label} is {dist:.0f} m from ({city.lat}, {city.lon}) — "
                f"outside the {default_radius_m} m default load radius"
            )


def test_all_cities_have_reasonable_demo_hour():
    for key, city in CITIES.items():
        assert 5.0 <= city.demo_hour <= 20.0, (
            f"{key} demo_hour={city.demo_hour} is outside the app slider range"
        )


def test_all_cities_use_iana_timezone_for_india():
    for key, city in CITIES.items():
        assert city.tz == "Asia/Kolkata", (
            f"{key} uses tz={city.tz}; all Indian cities should be Asia/Kolkata"
        )
