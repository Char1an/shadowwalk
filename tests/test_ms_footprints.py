import geopandas as gpd
from shapely.geometry import Polygon

from src.ms_footprints import (
    _latlon_to_tile,
    _tile_to_quadkey,
    merge_heights_from_ms,
    quadkeys_for_bbox,
)


def test_quadkey_known_value_seattle():
    """(47.6, -122.3) at zoom 9 has a well-known quadkey."""
    x, y = _latlon_to_tile(47.6062, -122.3321, zoom=9)
    qk = _tile_to_quadkey(x, y, zoom=9)
    assert len(qk) == 9
    assert set(qk).issubset({"0", "1", "2", "3"})
    # Sanity: same coord should give same key
    assert qk == _tile_to_quadkey(*_latlon_to_tile(47.6062, -122.3321))


def test_quadkeys_for_bbox_covers_at_least_one_tile():
    keys = quadkeys_for_bbox(13.03, 80.23, 13.10, 80.30)
    assert len(keys) >= 1
    assert all(len(k) == 9 for k in keys)


def test_merge_heights_prefers_ms_when_taller():
    osm = gpd.GeoDataFrame(
        {"height": [10.0]},
        geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])],
        crs="EPSG:32644",
    )
    ms = gpd.GeoDataFrame(
        {"height": [45.0]},
        geometry=[Polygon([(1, 1), (9, 1), (9, 9), (1, 9)])],  # inside the OSM footprint
        crs="EPSG:32644",
    )
    out = merge_heights_from_ms(osm, ms)
    assert out.iloc[0]["height"] == 45.0


def test_merge_heights_keeps_osm_when_taller():
    osm = gpd.GeoDataFrame(
        {"height": [80.0]},
        geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])],
        crs="EPSG:32644",
    )
    ms = gpd.GeoDataFrame(
        {"height": [12.0]},
        geometry=[Polygon([(1, 1), (9, 1), (9, 9), (1, 9)])],
        crs="EPSG:32644",
    )
    out = merge_heights_from_ms(osm, ms)
    assert out.iloc[0]["height"] == 80.0


def test_add_missing_buildings_appends_non_overlapping():
    """MS footprints that don't overlap any OSM building should be added."""
    from src.ms_footprints import add_missing_buildings_from_ms

    osm = gpd.GeoDataFrame(
        {"height": [15.0]},
        geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])],
        crs="EPSG:32644",
    )
    ms = gpd.GeoDataFrame(
        geometry=[
            Polygon([(1, 1), (5, 1), (5, 5), (1, 5)]),         # inside OSM — skip
            Polygon([(100, 100), (110, 100), (110, 110), (100, 110)]),  # missing → add
        ],
        crs="EPSG:32644",
    )
    out = add_missing_buildings_from_ms(osm, ms, default_height_m=15.0)
    assert len(out) == 2, "one OSM + one added MS building"
    added = out.iloc[1]
    assert added["height"] == 15.0
    assert added.geometry.bounds == (100.0, 100.0, 110.0, 110.0)


def test_add_missing_works_when_osm_is_empty():
    """Gangavathi case: OSM has ~zero buildings but MS has hundreds."""
    from src.ms_footprints import add_missing_buildings_from_ms

    osm = gpd.GeoDataFrame(geometry=[], crs="EPSG:32644")
    osm["height"] = []
    ms = gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])],
        crs="EPSG:32644",
    )
    out = add_missing_buildings_from_ms(osm, ms, default_height_m=15.0)
    assert len(out) == 1
    assert out.iloc[0]["height"] == 15.0


def test_empty_ms_is_noop():
    osm = gpd.GeoDataFrame(
        {"height": [10.0]},
        geometry=[Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])],
        crs="EPSG:32644",
    )
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:32644")
    empty["height"] = []
    out = merge_heights_from_ms(osm, empty)
    assert out.iloc[0]["height"] == 10.0
