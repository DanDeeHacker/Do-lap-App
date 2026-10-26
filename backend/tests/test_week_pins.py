"""Owner request 2026-10-26: the runner changes a day in Plán týdne — the change stands only where
the week's rules allow it, the rest of the week is laid again around it, and the sheet offers
alternatives for what can't be placed (metrics/week_plan.py: pins, options, preview)."""
from datetime import date, timedelta

from app.metrics import week_plan as WP

from .test_week_plan import MON, _a, _items, _runs

TUE, WED, THU, FRI, SAT, SUN = (MON + timedelta(days=k) for k in range(1, 7))


def _day(p, d):
    return next(x for x in p["days"] if x["date"] == d.isoformat())


def test_a_day_off_moves_the_run_and_keeps_the_week_under_its_target():
    base = WP.build(_a(), MON)
    p = WP.build(_a(), MON, None, {TUE.isoformat(): {"type": "volno"}})
    assert all(it["kind"] == "rest" for it in _day(p, TUE)["items"]) and _day(p, TUE)["pinned"]
    assert p["pins"][TUE.isoformat()]["status"] == "ok"
    km = sum(it["km"]["hi"] for _, it in _runs(p) if not it["optional"])
    assert km <= 46.2 and len(_runs(p)) >= len(_runs(base)) - 1          # the run went to another day, not lost
    assert not any(d == TUE for d, _ in _items(p, "strength") + _items(p, "ride"))


def test_an_easy_run_of_the_runners_size_shrinks_the_other_days():
    base = WP.build(_a(), MON)
    p = WP.build(_a(), MON, None, {SAT.isoformat(): {"type": "lehký", "km": 12}})
    sat = [it for d, it in _runs(p) if d == SAT]
    assert sat and sat[0]["type"] == "lehký" and sat[0]["km"]["hi"] == 12.0 and sat[0]["pinned"]
    assert p["pins"][SAT.isoformat()]["status"] == "ok"
    assert sum(it["km"]["hi"] for _, it in _runs(p) if not it["optional"]) <= 46.2
    others = lambda q: sum(it["km"]["hi"] for d, it in _runs(q) if d not in (SAT,) and it["type"] == "lehký")
    assert others(p) < others(base)


def test_a_size_over_the_rolling_ceiling_is_cut_and_says_why():
    # last week's heavy end leaves Wednesday less room than 12 km
    p = WP.build(_a(), MON, None, {WED.isoformat(): {"type": "lehký", "km": 12}})
    st = p["pins"][WED.isoformat()]
    wed = [it for d, it in _runs(p) if d == WED]
    assert wed and wed[0]["km"]["hi"] < 12 and st["status"] == "mod" and "strop" in st["why"]


def test_a_hard_session_the_day_after_the_long_run_is_refused_with_the_reason():
    # the long run on Sunday → a hard Monday of next week isn't in play; put the long run on Wednesday
    p = WP.build(_a(), MON, None, {WED.isoformat(): {"type": "dlouhý"}, THU.isoformat(): {"type": "kvalitní"}})
    assert [d for d, _ in _runs(p, "dlouhý")] == [WED]
    st = p["pins"][THU.isoformat()]
    assert st["status"] == "no" and "48 hodin" in st["why"]
    assert not any(d == THU for d, _ in _runs(p, "kvalitní"))
    assert all(abs((d - WED).days) >= 2 for d, _ in _runs(p, "kvalitní"))


def test_pain_refuses_intensity_and_options_offer_an_easy_run_or_another_day():
    a = _a(ctx={"painMod": True, "painWhy": "Bolest 4/10"})
    o = WP.options(a, MON, None, {}, THU.isoformat())
    by = {t["type"]: t for t in o["types"]}
    assert by["kvalitní"]["status"] == "no" and "Bolest 4/10" in by["kvalitní"]["why"]
    assert by["dlouhý"]["status"] == "no"
    assert any(x["kind"] == "type" and x["type"] == "lehký" for x in by["kvalitní"]["alts"])
    assert by["lehký"]["status"] in ("ok", "mod") and by["lehký"]["range"]["hi"] >= by["lehký"]["range"]["lo"]
    assert by["volno"]["status"] == "ok"


def test_options_show_what_else_moves_and_the_days_a_session_can_move_to():
    o = WP.options(_a(), MON, None, {}, SUN.isoformat())
    assert o["editable"] and o["currentType"] == "dlouhý"
    rest = next(t for t in o["types"] if t["type"] == "volno")
    assert rest["status"] == "ok" and rest["changes"]                      # the long run lands elsewhere
    assert o["moves"] and any(m["status"] != "no" for m in o["moves"])
    pv = WP.preview(_a(), MON, None, {}, SUN.isoformat(), {"type": "dlouhý"}, move_to=SAT.isoformat())
    assert pv["status"] in ("ok", "mod", "no") and isinstance(pv["changes"], list)


def test_a_race_day_and_past_days_cant_be_changed():
    a = _a(ctx={"races": [{"date": SAT.isoformat(), "name": "Půlmaraton", "km": 21.1, "priority": "A"}]})
    assert not WP.options(a, MON, None, {}, SAT.isoformat())["editable"]
    assert not WP.options(_a(), TUE, None, {}, MON.isoformat())["editable"]


def test_a_stopped_plan_keeps_no_run_pins():
    a = _a(override={"title": "Bolest omezuje pohyb", "kind": "acute"})
    p = WP.build(a, MON, None, {WED.isoformat(): {"type": "lehký"}, THU.isoformat(): {"type": "volno"}})
    assert p["pins"][WED.isoformat()]["status"] == "no" and "pozastavený" in p["pins"][WED.isoformat()]["why"]
    assert p["pins"][THU.isoformat()]["status"] == "ok"


def test_strength_pinned_on_a_day_before_the_long_run_is_refused():
    p = WP.build(_a(), MON, {"name": "Runner's must-have", "due": "A", "last": None}, {SAT.isoformat(): {"type": "posilování"}})
    st = p["pins"][SAT.isoformat()]
    assert st["status"] == "no" and "den před" in st["why"]


def test_the_api_saves_a_change_refuses_a_forbidden_one_and_undoes(client, db_session):
    from app.metrics import engine as E
    from .conftest import register
    rid = register(client, "pins1026@test.cz", "Plánovač", "runner").json()["runner_id"]
    today = E.today_date()
    r = client.get(f"/api/runners/{rid}/week-plan/options", params={"day": today.isoformat()})
    assert r.status_code == 200 and "types" in r.json()
    r = client.put(f"/api/runners/{rid}/week-plan/pins", json={"date": (today - timedelta(days=1)).isoformat(), "type": "volno"})
    assert r.status_code == 422                                              # the days behind are history
    r = client.put(f"/api/runners/{rid}/week-plan/pins", json={"date": today.isoformat(), "type": "závod"})
    assert r.status_code == 422
    r = client.put(f"/api/runners/{rid}/week-plan/pins", json={"date": today.isoformat(), "type": "volno"})
    if r.status_code == 200:                                                 # a runner without data has no plan to change
        from app import models
        runner = db_session.query(models.Runner).filter(models.Runner.id == rid).first()
        db_session.refresh(runner)
        assert (runner.planner_json or {}).get("dayPins", {}).get(today.isoformat(), {}).get("type") == "volno"
        assert client.delete(f"/api/runners/{rid}/week-plan/pins/{today.isoformat()}").status_code == 200
    else:
        assert r.status_code == 422
