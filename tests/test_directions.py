import networkx as nx
from shapely.geometry import LineString

from src.directions import (
    _bearing,
    _heading_word,
    _turn_word,
    build_directions,
    format_markdown,
)


def test_bearing_cardinals():
    # north
    assert abs(_bearing(0, 0, 0, 10) - 0) < 1e-6
    # east
    assert abs(_bearing(0, 0, 10, 0) - 90) < 1e-6
    # south
    assert abs(_bearing(0, 0, 0, -10) - 180) < 1e-6
    # west
    assert abs(_bearing(0, 0, -10, 0) - 270) < 1e-6


def test_heading_word():
    assert _heading_word(0) == "north"
    assert _heading_word(90) == "east"
    assert _heading_word(180) == "south"
    assert _heading_word(270) == "west"
    assert _heading_word(45) == "north-east"


def test_turn_words():
    assert _turn_word(0, 10) == "Continue straight"
    assert _turn_word(0, 90) == "Turn right"
    assert _turn_word(0, -90) == "Turn left"
    assert _turn_word(0, 180) == "Make a sharp left"  # ambiguous, we pick one


def _tiny_route_graph():
    """S → A on 'Ranganathan St' → B on 'North Usman Rd' (a right turn)."""
    g = nx.MultiDiGraph()
    g.add_node("S", x=0.0, y=0.0)
    g.add_node("A", x=0.0, y=200.0)      # 200 m north
    g.add_node("B", x=180.0, y=200.0)    # then 180 m east
    g.add_edge("S", "A", length=200.0, name="Ranganathan St",
               geometry=LineString([(0, 0), (0, 200)]))
    g.add_edge("A", "B", length=180.0, name="North Usman Rd",
               geometry=LineString([(0, 200), (180, 200)]))
    return g


def test_build_directions_produces_two_steps_with_turn():
    g = _tiny_route_graph()
    steps = build_directions(g, ["S", "A", "B"], alpha=0.0)
    assert len(steps) == 2
    assert "north" in steps[0].text.lower()
    assert "Ranganathan St" in steps[0].text
    assert "200 m" in steps[0].text
    assert "Turn right" in steps[1].text
    assert "North Usman Rd" in steps[1].text


def test_directions_collapse_consecutive_same_street():
    g = nx.MultiDiGraph()
    g.add_node("S", x=0, y=0); g.add_node("A", x=0, y=100); g.add_node("B", x=0, y=250)
    g.add_edge("S", "A", length=100, name="Long St",
               geometry=LineString([(0, 0), (0, 100)]))
    g.add_edge("A", "B", length=150, name="Long St",
               geometry=LineString([(0, 100), (0, 250)]))
    steps = build_directions(g, ["S", "A", "B"])
    assert len(steps) == 1
    assert "250 m" in steps[0].text  # 100+150 collapsed


def test_format_markdown_includes_total():
    g = _tiny_route_graph()
    md = format_markdown(build_directions(g, ["S", "A", "B"]))
    assert "1." in md and "2." in md
    assert "total 380 m" in md


def test_format_markdown_empty_path():
    md = format_markdown([])
    assert "no directions" in md.lower()
