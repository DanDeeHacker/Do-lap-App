"""Desktop stat rail choice (redesign OPT-5) persists in user settings."""
from .conftest import register


def test_rail_cards_default_none_then_persist(client):
    register(client, "rail@test.cz", "Rail Test", "runner")
    s = client.get("/api/auth/settings").json()
    assert s["rail_cards"] is None
    r = client.patch("/api/auth/settings", json={"rail_cards": ["week", "load", "week", "bogus", "hrv"]})
    assert r.status_code == 200
    # unknown ids dropped, duplicates removed, order kept
    assert r.json()["rail_cards"] == ["week", "load", "hrv"]
    assert client.get("/api/auth/settings").json()["rail_cards"] == ["week", "load", "hrv"]


def test_other_settings_untouched_by_rail_patch(client):
    register(client, "rail2@test.cz", "Rail Two", "runner")
    client.patch("/api/auth/settings", json={"notify_drift": False})
    client.patch("/api/auth/settings", json={"rail_cards": ["recovery"]})
    s = client.get("/api/auth/settings").json()
    assert s["notify_drift"] is False and s["rail_cards"] == ["recovery"]
