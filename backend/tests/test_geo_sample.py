"""Phase 3b: OSM/ZABAGED surface classification of a run's GPS track."""
import os

import pytest

from app.metrics import geo_sample as G


def test_surface_class_mapping():
    assert G._surface_class("asphalt") == "paved"
    assert G._surface_class("fine_gravel") == "compact"
    assert G._surface_class("ground") == "soft"
    assert G._surface_class(None) is None
    assert G._surface_class("weird_value") is None


def test_classify_paved_road():
    ways = [{"tags": {"highway": "residential", "surface": "asphalt"}},
            {"tags": {"highway": "tertiary", "surface": "paving_stones"}}]
    c = G._classify(ways, "osm")
    assert c["surfaceClass"] == "paved" and c["onTrail"] is False and c["coverage"] == 1.0


def test_classify_soft_trail():
    ways = [{"tags": {"highway": "path", "surface": "ground"}},
            {"tags": {"highway": "track", "surface": "dirt"}},
            {"tags": {"highway": "footway"}}]  # no surface tag
    c = G._classify(ways, "osm")
    assert c["surfaceClass"] == "soft" and c["onTrail"] is True
    assert 0 < c["coverage"] < 1.0


def test_to_engine_surface():
    assert G.to_engine_surface({"surfaceClass": "soft", "onTrail": True, "coverage": 0.8}) == "trail"
    assert G.to_engine_surface({"surfaceClass": "paved", "onTrail": False, "coverage": 0.9}) == "road"
    assert G.to_engine_surface({"surfaceClass": "unknown", "onTrail": False, "coverage": 0.1}) is None


def test_in_czech_republic_and_downsample():
    assert G.in_czech_republic([(50.09, 14.42)]) is True
    assert G.in_czech_republic([(40.7, -74.0)]) is False
    assert len(G.downsample([(50.0 + i * 1e-4, 14.4) for i in range(100)], n=10)) == 10


@pytest.mark.skipif(not os.environ.get("RUN_NET"), reason="live network (set RUN_NET=1)")
def test_overpass_live():
    r = G.overpass_surface([(50.0903, 14.4006)])
    assert r is None or "surfaceClass" in r
