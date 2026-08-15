import networkx as nx

from src.routing import make_weight_fn, shortest_path


def _diamond_graph():
    """
    Two parallel paths between S and T:
      S -> A -> T (length 100 total, no shade)
      S -> B -> T (length 130 total, fully shaded)
    """
    g = nx.MultiDiGraph()
    for n in ("S", "A", "B", "T"):
        g.add_node(n)
    g.add_edge("S", "A", length=50, shade_score=0.0)
    g.add_edge("A", "T", length=50, shade_score=0.0)
    g.add_edge("S", "B", length=65, shade_score=1.0)
    g.add_edge("B", "T", length=65, shade_score=1.0)
    return g


def test_alpha_zero_prefers_shortest():
    g = _diamond_graph()
    assert shortest_path(g, "S", "T", alpha=0.0) == ["S", "A", "T"]


def test_high_alpha_prefers_shade_even_when_longer():
    g = _diamond_graph()
    # At alpha=1.0, shaded route weight ≈ 0, sunny route weight = 100 → shade wins.
    assert shortest_path(g, "S", "T", alpha=1.0) == ["S", "B", "T"]


def test_snap_distance_reports_meaningful_metres():
    """Regression: users clicking outside the loaded neighbourhood were
    silently snapped to a distant graph node. `snap_distance_m` gives us
    the number to surface as a warning."""
    import networkx as nx
    from src.routing import snap_distance_m

    # Metric-CRS graph (as produced by `load_area` / `_reproject_graph`)
    # near central Chennai — two T. Nagar nodes in UTM zone 44 N metres.
    g = nx.MultiDiGraph()
    g.graph["crs"] = "EPSG:32644"
    g.add_node(1, x=634640, y=1443090, _lat=13.0440, _lon=80.2320)
    g.add_node(2, x=635180, y=1442590, _lat=13.0395, _lon=80.2370)
    g.add_edge(1, 2, length=700.0)
    # Query at the exact node → snap distance ≈ 0 m
    assert snap_distance_m(g, 13.0440, 80.2320) < 5.0
    # Query 4 km north (Anna Nagar) → snap distance is thousands of metres
    assert snap_distance_m(g, 13.0820, 80.2320) > 3000.0


def test_summarize_route_matches_router_choice_with_parallel_edges():
    """Regression: on MultiDiGraphs with parallel edges, `summarize_route`
    used to always pick the shortest — but the router picks the min-cost one.
    They must agree."""
    import networkx as nx
    from src.metrics import summarize_route

    g = nx.MultiDiGraph()
    g.add_node("S"); g.add_node("T")
    # Two parallel edges S→T: fast+sunny vs slow+shady.
    g.add_edge("S", "T", key=0, length=100.0, shade_score=0.0)
    g.add_edge("S", "T", key=1, length=140.0, shade_score=1.0)

    # α=0.9 → shade edge cost = 140*(1-0.9)=14 < 100 → router picks shady.
    # summarize_route with the same α must agree and report high shade.
    summ = summarize_route(g, ["S", "T"], alpha=0.9)
    assert summ.distance_m == 140.0, f"expected 140 m (shady edge), got {summ.distance_m}"
    assert summ.shaded_fraction == 1.0

    # α=0.0 baseline still picks the shortest.
    summ0 = summarize_route(g, ["S", "T"], alpha=0.0)
    assert summ0.distance_m == 100.0


def test_weight_fn_bounds():
    import pytest
    with pytest.raises(ValueError):
        make_weight_fn(1.5)
