import json

from src import geocode as gc


def test_offline_returns_empty(monkeypatch, tmp_path):
    """Network failure must not raise — the UI needs a stable degradation."""
    monkeypatch.setattr(gc, "CACHE", tmp_path)

    def boom(*a, **kw):
        raise ConnectionError("simulated offline")
    monkeypatch.setattr(gc.requests, "get", boom)

    assert gc.geocode("Marina Beach") == []


def test_uses_cache_on_second_call(monkeypatch, tmp_path):
    monkeypatch.setattr(gc, "CACHE", tmp_path)

    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return [
                {"display_name": "Marina Beach, Chennai", "lat": "13.0500", "lon": "80.2825"},
            ]

    def fake_get(*a, **kw):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(gc.requests, "get", fake_get)

    first = gc.geocode("Marina Beach")
    second = gc.geocode("Marina Beach")
    assert first == second
    assert first[0]["lat"] == 13.05
    assert calls["n"] == 1, "second geocode call must hit disk cache, not network"


def test_empty_query_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setattr(gc, "CACHE", tmp_path)

    def boom(*a, **kw):
        raise AssertionError("should not have called network for empty query")
    monkeypatch.setattr(gc.requests, "get", boom)

    assert gc.geocode("") == []
    assert gc.geocode("   ") == []
