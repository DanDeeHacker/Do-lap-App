"""v0.12.13 — shoes per run: the run's shoe (pick > Garmin gear > default), km per shoe, the
transition window from the first run in the shoe, rotation by the pairs actually run in, and
the Garmin gear fetched with the sync."""
from datetime import timedelta
from types import SimpleNamespace as NS

from app import models
from app.metrics import engine as E
from app.metrics import runner_factors as RF
from app.routers import integrations as I
from .test_guidance import _runner


def _day(n):
    return (E.today_date() - timedelta(days=n)).isoformat()


def _shoe(i, **kw):
    base = dict(id=i, brand="Nike", model=f"Pegasus {i}", category="daily", drop_mm=10, stack_mm=None, carbon=False,
                first_used=_day(200), retired_at=None, is_default=False, garmin_uuid=None)
    base.update(kw)
    return NS(**base)


def _act(n, **kw):
    base = dict(sport="running", started_at=_day(n), shoe_id=None, gear_uuid=None, distance_km=10.0)
    base.update(kw)
    return NS(**base)


def test_run_shoe_pick_then_gear_then_default():
    shoes = [_shoe(1, is_default=True), _shoe(2, garmin_uuid="g-2")]
    assert RF.run_shoe_id(_act(3), shoes) == 1                              # the default
    assert RF.run_shoe_id(_act(3, gear_uuid="g-2"), shoes) == 2             # Garmin gear beats the default
    assert RF.run_shoe_id(_act(3, gear_uuid="g-2", shoe_id=1), shoes) == 1  # the runner's pick beats both
    assert RF.run_shoe_id(_act(3, shoe_id=0), shoes) is None                # "none of mine"
    assert RF.run_shoe_id(_act(3, sport="cycling"), shoes) is None
    assert RF.run_shoe_id(_act(300), shoes) is None                         # before the default's first use


def test_rotation_counts_pairs_actually_run_in():
    shoes = [_shoe(1), _shoe(2)]
    today = E.today_date()
    assert RF.shoe_state(shoes, None, today)["rotation"]["n"] == 2          # without runs: the old rule
    one = [_act(n, shoe_id=1) for n in (2, 5, 9)]
    st = RF.shoe_state(shoes, None, today, one)
    assert st["rotation"] is None and st["byRun"]                          # only one pair in use
    both = one + [_act(n, shoe_id=2) for n in (3, 7)]
    assert RF.shoe_state(shoes, None, today, both)["rotation"]["n"] == 2


def test_transition_opens_on_the_first_run_in_the_shoe():
    old = _shoe(1, drop_mm=10, first_used=_day(300))
    low = _shoe(2, drop_mm=4, first_used=_day(60))                         # bought 60 days ago…
    today = E.today_date()
    assert RF.shoe_state([old, low], None, today)["transition"] is None     # by date: the 6 weeks are over
    runs = [_act(n, shoe_id=1) for n in (40, 30, 20)] + [_act(10, shoe_id=2)]   # …first run in it 10 days ago
    tr = RF.shoe_state([old, low], None, today, runs)["transition"]
    assert tr and tr["id"] == 2 and tr["kind"] == "drop" and tr["day"] == 11 and tr["since"] == _day(10)


def test_api_pick_default_pairing_and_km(client, db_session):
    rid, _ = _runner(client, db_session, "spr1@test.cz", days=40)
    a = client.post(f"/api/runners/{rid}/shoes", json={"brand": "HOKA", "model": "Clifton 9", "category": "cushioned",
                                                        "first_used": _day(60)}).json()["shoes"][0]
    b = client.post(f"/api/runners/{rid}/shoes", json={"brand": "Nike", "model": "Pegasus 41", "category": "daily",
                                                        "first_used": _day(60)}).json()["shoes"][1]
    d = client.patch(f"/api/runners/{rid}/shoes/{a['id']}", json={"is_default": True}).json()
    km_all = sum(x.distance_km or 0 for x in db_session.query(models.Activity).filter(
        models.Activity.runner_id == rid, models.Activity.sport == "running", models.Activity.started_at >= _day(60)))
    by = {s["id"]: s for s in d["shoes"]}
    assert d["byRun"] and abs(by[a["id"]]["kmSince"] - round(km_all, 1)) < 0.2 and by[b["id"]]["kmSince"] == 0
    run = (db_session.query(models.Activity).filter(models.Activity.runner_id == rid, models.Activity.sport == "running")
           .order_by(models.Activity.started_at.desc()).first())
    picked = client.patch(f"/api/runners/{rid}/activities/{run.id}/shoe", json={"shoe_id": b["id"]}).json()["shoe"]
    assert picked["id"] == b["id"] and picked["source"] == "pick"
    by = {s["id"]: s for s in client.get(f"/api/runners/{rid}/shoes").json()["shoes"]}
    assert by[b["id"]]["runsSince"] == 1
    # back to automatic, then the gear of that run paired with the second pair
    client.patch(f"/api/runners/{rid}/activities/{run.id}/shoe", json={"shoe_id": None})
    run.gear_uuid = "uuid-peg"
    db_session.commit()
    client.patch(f"/api/runners/{rid}/shoes/{b['id']}", json={"garmin_uuid": "uuid-peg"})
    tr = client.get(f"/api/runners/{rid}/activities/{run.id}/track").json()
    assert tr["shoe"]["id"] == b["id"] and tr["shoe"]["source"] == "garmin"
    # one default at most
    d = client.patch(f"/api/runners/{rid}/shoes/{b['id']}", json={"is_default": True}).json()
    assert [s["id"] for s in d["shoes"] if s["is_default"]] == [b["id"]]


def test_fetch_gear_records_the_gear_of_recent_runs(client, db_session):
    rid, _ = _runner(client, db_session, "spr2@test.cz", days=20)
    for a in db_session.query(models.Activity).filter(models.Activity.runner_id == rid):
        a.provider, a.external_id = "garmin", f"x{a.id}"
    db_session.commit()

    class FakeGarmin:
        def get_activity_gear(self, ext):
            return [{"uuid": "uuid-1", "gearTypeName": "Shoes", "displayName": "Moje Pegasy"}]
    n = I.fetch_gear(db_session, rid, FakeGarmin())
    assert 0 < n <= I.GEAR_CAP
    runner = db_session.query(models.Runner).filter_by(id=rid).one()
    assert runner.onboarding_json["garminGear"]["uuid-1"]["name"] == "Moje Pegasy"
    gear = client.get(f"/api/runners/{rid}/shoes").json()["garminGear"]
    assert gear[0]["uuid"] == "uuid-1" and gear[0]["runs"] == n and gear[0]["pairedTo"] is None
