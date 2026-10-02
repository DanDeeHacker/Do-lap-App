"""Feedback #151 — race effort levels: training / moderate / all-out with pace,
heart rate and strategy, and the recommended level from the runner's capacity."""
from datetime import timedelta

from app.metrics import engine as E

from .conftest import login


def _add(client, rid, km, prio, days=3, ascent=None):
    d = (E.today_date() + timedelta(days=days)).isoformat()
    body = {"date": d, "name": f"Test {km}", "distance_km": km, "priority": prio}
    if ascent is not None:
        body["ascent_m"] = ascent
    races = client.post(f"/api/runners/{rid}/races", json=body).json()["races"]
    return next(x for x in races if x["name"] == f"Test {km}")


def test_race_plan_levels_and_recommendation(client):
    me = login(client, "adela@demo.cz").json()
    rid = me["runner_id"]
    race = _add(client, rid, 10, "B")
    p = client.get(f"/api/runners/{rid}/races/{race['id']}/plan").json()
    assert [lv["id"] for lv in p["levels"]] == ["trénink", "střední", "naplno"]
    assert p["recommended"] in ("trénink", "střední", "naplno") and p["why"]
    paces = [lv["pace"] for lv in p["levels"]]
    if all(paces):
        assert paces[0] > paces[1] > paces[2]               # harder level = faster pace
    for lv in p["levels"]:
        assert lv["strategy"] and lv["rpe"] and lv["hr"][0] < lv["hr"][1]
    assert p["levels"][2]["recoveryDays"] >= 2


def test_training_race_and_long_race_step_down(client):
    rid = login(client, "adela@demo.cz").json()["runner_id"]
    c = _add(client, rid, 5, "C")
    assert client.get(f"/api/runners/{rid}/races/{c['id']}/plan").json()["recommended"] == "trénink"
    ultra = _add(client, rid, 80, "B", days=4, ascent=2500)
    p = client.get(f"/api/runners/{rid}/races/{ultra['id']}/plan").json()
    assert p["recommended"] != "naplno"
    assert any("Nad 75 min" in t for t in p["levels"][2]["strategy"])
    assert client.get(f"/api/runners/{rid}/races/nope/plan").status_code == 404
