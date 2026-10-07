"""Owner request 2026-10-05: bedtime mobility — mobility exercises in the library, mobility
programmes by the kind of day and by body region, and the evening report's pick of 3–8
exercises by the day's activities, with a link to save / do the programme."""
from datetime import date

from app import models
from app import programs_library as PL
from app.metrics import engine as E
from app.metrics import mobility as MOB

from .conftest import register

DAY = date(2026, 10, 5)


def _act(sport="running", km=8.0, mins=45, rpe=None, aid=1):
    return {"id": aid, "date": DAY.isoformat(), "sport": sport, "run": sport == "running", "km": km if sport == "running" else None,
            "min": mins, "rpe": rpe, "title": sport}


def _a(easy=8.0, hard_ids=()):
    return {"guidance": {"planCtx": {"easyKm": easy}},
            "capacity": {"channels": {"intensity": {"week7": [{"id": i, "date": DAY.isoformat(), "value": 18} for i in hard_ids]}}}}


def test_library_has_tagged_mobility_exercises_and_programmes():
    mob = {k: v for k, v in PL.EXERCISES.items() if v.get("kind") == "mobility"}
    assert len(mob) >= 20 and all(v["steps"] and v["dose"] and v["min"] for v in mob.values())
    progs = [p for p in PL.PROGRAMS if p["group"] == "mobility"]
    days = {p["day"] for p in progs if p["sub"] == "day"}
    assert days == {"lehký", "kvalitní", "dlouhý", "kolo", "plavání", "sedavý"}
    assert len([p for p in progs if p["sub"] == "region"]) >= 5
    for p in progs:
        assert 3 <= len(p["exercises"]) <= 8 and all(PL.EXERCISES[x].get("kind") == "mobility" for x in p["exercises"])
        assert all(r in PL.REFERENCES for r in p["refs"]) and p["minutes"] == sum(PL.EXERCISES[x]["min"] for x in p["exercises"])
    # no protection claim: the evidence says what stretching doesn't do
    assert all("nepředchází" in p["evidence"] for p in progs)


def test_the_day_picks_the_programme():
    assert MOB.day_kinds([_act(km=16)], _a(), DAY) == ["dlouhý"]
    assert MOB.day_kinds([_act(km=6, mins=95)], _a(), DAY) == ["dlouhý"]
    assert MOB.day_kinds([_act(km=8, aid=7)], _a(hard_ids=[7]), DAY) == ["kvalitní"]
    assert MOB.day_kinds([_act(km=8, rpe=8)], _a(), DAY) == ["kvalitní"]
    assert MOB.day_kinds([_act(km=7)], _a(), DAY) == ["lehký"]
    assert MOB.day_kinds([_act("cycling", mins=90)], _a(), DAY) == ["kolo"]
    assert MOB.day_kinds([_act("swimming", mins=40)], _a(), DAY) == ["plavání"]
    assert MOB.day_kinds([_act("strength", mins=40)], _a(), DAY) == ["posilování"]
    assert MOB.day_kinds([_act("walking", mins=60)], _a(), DAY) == ["sedavý"]
    assert MOB.day_kinds([], _a(), DAY) == ["sedavý"]
    assert MOB.day_kinds([_act("cycling", mins=60, aid=2), _act(km=7)], _a(), DAY) == ["lehký", "kolo"]


def test_evening_pick_with_a_second_sport_and_near_bedtime(client, db_session):
    rid = register(client, "mob1005@test.cz", "Mobilita", "runner").json()["runner_id"]
    m = MOB.evening(db_session, rid, _a(), DAY, [_act(km=7), _act("cycling", mins=60, aid=2)], bed="22:30", now_min=20 * 60)
    ids = [x["id"] for x in m["exercises"]]
    assert m["program"]["key"] == "mob_run" and 3 <= len(ids) <= 8 and ids[-1] == "mob_breathing"
    extra = [x for x in m["exercises"] if x["extraFrom"]]
    assert extra and all(x["extraFrom"] == "Mobilita po kole" for x in extra) and not m["short"]
    assert m["minutes"] == sum(x["min"] for x in m["exercises"]) and "lehký běh" in m["why"] and m["also"] == "K tomu kolo."
    late = MOB.evening(db_session, rid, _a(), DAY, [_act(km=16)], bed="22:30", now_min=22 * 60 + 20)
    assert late["short"] and len(late["exercises"]) == 3 and late["exercises"][-1]["id"] == "mob_breathing"
    after_midnight = MOB.evening(db_session, rid, _a(), DAY, [], bed="23:00", now_min=30)
    assert after_midnight["short"]
    assert MOB.note(m).startswith("Dnes lehký běh")


def test_a_painful_calf_flags_the_calf_stretch(client, db_session):
    rid = register(client, "mob1005b@test.cz", "Lýtko", "runner").json()["runner_id"]
    db_session.add(models.Checkin(runner_id=rid, submitted_at=f"{DAY.isoformat()}T07:00:00", pain_score=3,
                                  pain_points=[{"region": "Lýtko (gastrocnemius)", "side": "L"}]))
    db_session.commit()
    m = MOB.evening(db_session, rid, _a(), DAY, [_act(km=7)], bed="22:30", now_min=20 * 60)
    flagged = {x["id"] for x in m["exercises"] if x["careful"]}
    assert "mob_calf_wall" in flagged and "mob_hip_flexor" not in flagged


def test_saving_the_programme_and_the_evening_report(client, db_session, monkeypatch):
    rid = register(client, "mob1005c@test.cz", "Večer", "runner").json()["runner_id"]
    from app.metrics import daily_report as DR
    with E.today_pinned(DAY):
        r = DR.build(db_session, rid, "evening")
    m = r["mobility"]
    assert m["program"]["key"] == "mob_sedentary" and not m["saved"] and r["notes"]["mobility"]
    p = client.post(f"/api/runners/{rid}/self-programs", json={"template": "mob_sedentary"}).json()
    assert p["template"] == "mob_sedentary" and p["weeks"] is None and len(p["exercises"]) == 8
    again = client.post(f"/api/runners/{rid}/self-programs", json={"template": "mob_sedentary"}).json()
    assert again["id"] == p["id"]                           # saving twice keeps one programme
    with E.today_pinned(DAY):
        r2 = DR.build(db_session, rid, "evening")
    assert r2["mobility"]["saved"] and r2["mobility"]["savedId"] == p["id"]


def test_every_programme_exercise_has_a_figure():
    """Feedback railway#203 — a demonstration for every exercise of every programme."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "exfigure.tsx").read_text(encoding="utf-8")
    figs = set(re.findall(r"^  (\w+): \{", src, re.M)) | set(re.findall(r"^SPECS\.(\w+) =", src, re.M))
    used = {x for p in PL.PROGRAMS for x in p["exercises"]}
    assert not used - figs, sorted(used - figs)
