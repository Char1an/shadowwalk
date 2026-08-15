import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, Point, Polygon

from src.shade import build_shadow_layer, compute_edge_shade


def _tiny_graph_with_blocker():
    """One east-west street with a tall building immediately south of it."""
    g = nx.MultiDiGraph()
    g.add_node(1, x=0.0, y=0.0)
    g.add_node(2, x=50.0, y=0.0)
    line = LineString([(0, 0), (50, 0)])
    g.add_edge(1, 2, geometry=line, length=50.0)

    # 50m-tall building 5m south of the street (sun is to the south → building blocks)
    building = Polygon([(0, -30), (50, -30), (50, -5), (0, -5)])
    gdf = gpd.GeoDataFrame({"height": [50.0]}, geometry=[building], crs="EPSG:32644")
    return g, gdf


def test_high_sun_from_south_is_shaded_by_tall_building_south():
    g, gdf = _tiny_graph_with_blocker()
    # Sun almost overhead but slightly to the south → tall south wall casts shadow northward.
    compute_edge_shade(g, gdf, sun_azimuth_deg=180.0, sun_elevation_deg=45.0)
    (_, _, data), = ((u, v, d) for u, v, d in g.edges(data=True))
    assert data["shade_score"] == 1.0


def test_night_is_all_shaded():
    g, gdf = _tiny_graph_with_blocker()
    compute_edge_shade(g, gdf, sun_azimuth_deg=180.0, sun_elevation_deg=-5.0)
    (_, _, data), = ((u, v, d) for u, v, d in g.edges(data=True))
    assert data["shade_score"] == 1.0


def test_sun_from_north_leaves_street_exposed():
    g, gdf = _tiny_graph_with_blocker()
    # Building is south, sun is from the north → no blocker in the sun direction.
    compute_edge_shade(g, gdf, sun_azimuth_deg=0.0, sun_elevation_deg=45.0)
    (_, _, data), = ((u, v, d) for u, v, d in g.edges(data=True))
    assert data["shade_score"] == 0.0


def test_low_sun_casts_longer_shadow_than_high_sun():
    """Shadow length ∝ 1/tan(elevation): 30° sun casts a shadow ~2× longer than 60°."""
    b = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    gdf = gpd.GeoDataFrame({"height": [20.0]}, geometry=[b], crs="EPSG:32644")
    high = build_shadow_layer(gdf, sun_azimuth_deg=180.0, sun_elevation_deg=60.0)
    low = build_shadow_layer(gdf, sun_azimuth_deg=180.0, sun_elevation_deg=30.0)
    assert low.iloc[0].area > 1.5 * high.iloc[0].area


def test_night_marks_every_edge_shaded():
    g, gdf = _tiny_graph_with_blocker()
    compute_edge_shade(g, gdf, sun_azimuth_deg=180.0, sun_elevation_deg=-10.0)
    for _, _, data in g.edges(data=True):
        assert data["shade_score"] == 1.0


def test_max_shadow_length_is_capped_in_metres():
    """Regression: a 100 m tower at 3° sun elevation used to cast a ~1.9 km
    shadow because the length cap was applied to the *multiplier* instead of
    the actual shadow length in metres."""
    from src.shade import MAX_SHADOW_LENGTH_M, build_shadow_layer

    tower = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    gdf = gpd.GeoDataFrame({"height": [100.0]}, geometry=[tower], crs="EPSG:32644")
    layer = build_shadow_layer(gdf, sun_azimuth_deg=180.0, sun_elevation_deg=3.0)
    # Shadow extends northward from the building; bounds max y must be
    # capped by MAX_SHADOW_LENGTH_M + a bit of buffer / footprint depth.
    _, _, _, ymax = layer.iloc[0].bounds
    assert ymax <= MAX_SHADOW_LENGTH_M + 20.0, (
        f"shadow ymax={ymax:.1f} m exceeds cap {MAX_SHADOW_LENGTH_M} m"
    )


def test_night_clears_shadow_layer_on_graph():
    """Regression: switching from day → night must clear graph.graph[shadow_layer]
    so downstream viz doesn't render stale daytime shadows on a night map."""
    g, gdf = _tiny_graph_with_blocker()
    compute_edge_shade(g, gdf, sun_azimuth_deg=180.0, sun_elevation_deg=45.0)
    assert "shadow_layer" in g.graph and len(g.graph["shadow_layer"]) > 0

    compute_edge_shade(g, gdf, sun_azimuth_deg=180.0, sun_elevation_deg=-5.0)
    assert len(g.graph["shadow_layer"]) == 0


def test_tree_cover_adds_shade():
    """A canopy polygon covering the street should register as shaded even if no buildings do."""
    g = nx.MultiDiGraph()
    g.add_node(1, x=0.0, y=100.0); g.add_node(2, x=50.0, y=100.0)
    g.add_edge(1, 2, geometry=LineString([(0, 100), (50, 100)]), length=50.0)
    # A footprint sitting far away so its shadow doesn't reach the street.
    b = Polygon([(500, 500), (510, 500), (510, 510), (500, 510)])
    gdf = gpd.GeoDataFrame({"height": [5.0]}, geometry=[b], crs="EPSG:32644")
    canopy = gpd.GeoSeries([Polygon([(-10, 90), (60, 90), (60, 110), (-10, 110)])],
                           crs="EPSG:32644")
    compute_edge_shade(g, gdf, sun_azimuth_deg=180.0, sun_elevation_deg=60.0, tree_cover=canopy)
    (_, _, data), = ((u, v, d) for u, v, d in g.edges(data=True))
    assert data["shade_score"] == 1.0
