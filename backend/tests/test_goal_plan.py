"""Trénink k cíli, stage 1 (owner request and decisions 2026-10-12): the requirements from
the studies, the week-by-week projection under the app's own limits, the verdict with the
real date and the alternatives, and the goal API."""
from datetime import timedelta

from app.metrics import engine as E
from app.metrics import goal_plan as G
from app.assistant import knowledge as K
from .test_guidance import _runner


def _st(km=30.0, long=12.0, climb=100.0, runs=4):
    w = [{"km": km, "long": long, "down": climb, "up": climb, "downRun": climb / 2, "upRun": climb / 2, "runs": runs}
         for _ in range(G.HIST_WEEKS)]
    return {"today": "2026-10-12", "start": "2026-10-19", "weeks": w, "long30": long, "down30": climb / 2,
            "up30": climb / 2, "marginWeek": 0.15, "marginRun": 0.10, "experience": None,
            "everHalf": False, "everMarathon": False, "limited": None}


def _race(km, date, aim="finish", **kw):
    return {"kind": "race", "km": km, "date": date, "aim": aim, **kw}


def test_requirements_follow_the_studies():
    m = G.requirements(_race(42.2, "2027-05-01"))
    assert m["week"]["base"] == 55 and m["week"]["need"] == 58          # 29 km long run at most 50 % of the week
    assert m["long"]["need"] == 29 and m["longCount"] == {**m["longCount"], "need": 1, "km": 29.0}
    t = G.requirements(_race(42.2, "2027-05-01", aim="time"))
    assert t["week"]["need"] == 65 and t["long"]["need"] == 32 and t["longCount"]["need"] == 2
    h = G.requirements(_race(21.1, "2027-05-01"))
    assert h["week"]["need"] == 37 and h["long"]["need"] == 18 and "longCount" not in h
    assert G.requirements(_race(21.1, "2027-05-01", aim="time"))["long"]["need"] == 21
    assert G.requirements(_race(10, "2027-05-01"))["week"]["need"] == 25
    for k in ("fokkema-et-al-2020", "mohseni-et-al-2019", "rasmussen-et-al-2013", "doherty-et-al-2019",
              "toresdahl-et-al-2021"):
        assert k in {s for r in m.values() for s in r["sources"]}
        assert k in K.summary_by_id()                                     # every source is in the library


def test_trail_turns_climb_into_requirements():
    tr = G.requirements(_race(30, "2027-06-01", ascentM=1500))
    assert G.is_trail(_race(30, "2027-06-01", ascentM=1500))
    assert tr["long"]["need"] == 21 and tr["descentRun"]["need"] == 900 and tr["descentWeek"]["need"] == 1500
    assert tr["descSessions"]["need"] == 10
    flat = 30 + 7.92 * 1.5                                               # Scarf: climb as flat km
    assert tr["week"]["need"] >= max(45.0, G._interp(flat, 0, 0)) - 0.01
    assert G.requirements(_race(100, "2027-08-01", ascentM=5000))["long"]["need"] == G.TRAIL_LONG_MAX


def test_taper_is_two_weeks_for_the_marathon():
    assert G.taper_weeks(_race(42.2, "2027-05-01")) == 2
    assert G.taper_weeks(_race(21.1, "2027-05-01")) == 2
    assert G.taper_weeks(_race(10, "2027-05-01")) == 1
    assert G.taper_weeks({"kind": "free", "date": "2027-05-01"}) == 0


def test_the_projection_keeps_the_limits():
    req = G.requirements(_race(42.2, "2027-12-01", aim="time"))
    for path, rise in ((G.SAFE, 0.15), (G.RISK, 0.20)):
        st = _st()
        p = G.project(req, st, path)
        hist = [w["km"] for w in st["weeks"]]
        for row in p["rows"]:
            ref = max(hist[-2:])
            assert row["km"] <= ref * (1 + rise) + 0.11, (path["key"], row)           # Damsted 2019
            assert row["km"] <= 1.5 * sum(hist[-4:]) / 4 + 0.11                       # Toresdahl 2022
            assert row["long"] <= row["km"] * G.LONG_SHARE + 0.11                     # the 50 % share
            hist.append(row["km"])
    safe, risk = G.project(req, _st(), G.SAFE), G.project(req, _st(), G.RISK)
    assert risk["readyWeek"] < safe["readyWeek"]


def test_verdicts_real_date_and_alternatives():
    st = _st()
    near = G.evaluate(_race(42.2, "2027-01-10"), st)                  # 13 weeks for a 30 km/week runner
    assert near["verdict"] == "no" and near["realDate"] > "2027-01-10"
    assert "Reálný termín je od" in near["text"]
    kinds = {a["kind"] for a in near["alternatives"]}
    assert {"later", "shorter", "risk"} <= kinds
    half = next(a for a in near["alternatives"] if a["kind"] == "shorter")
    assert half["goal"]["km"] == 21.1 and half["verdict"] == "ok"
    far = G.evaluate(_race(42.2, near["realDate"]), st)               # the real date it gave is indeed reachable
    assert far["verdict"] == "ok" and "alternatives" not in far
    assert {n["key"] for n in far["notes"]} >= {"half", "freq", "taper"}   # first marathon, no half yet
    tight_date = (G._d(st["start"]) + timedelta(days=7 * (near["safe"]["readyWeek"] + 2) - 1)).isoformat()
    assert G.evaluate(_race(42.2, tight_date), st)["verdict"] == "tight"
    t = G.evaluate(_race(21.1, "2027-01-10", aim="time"), st)
    assert any(a["kind"] == "finish" for a in t.get("alternatives", [])) or t["verdict"] == "ok"


def test_no_data_means_no_projection():
    st = _st(runs=0)
    r = G.evaluate(_race(21.1, "2027-05-01"), st)
    assert r["verdict"] == "unknown" and "safe" not in r


def test_free_goal(client, db_session):
    st = _st()
    r = G.evaluate({"kind": "free", "date": "2027-03-01", "free": {"weeklyKm": 50, "longKm": 25}}, st)
    assert [q["key"] for q in r["requirements"]] == ["week", "long"] and r["taperWeeks"] == 0
    assert r["verdict"] in ("ok", "tight", "no")


def test_goal_api(client, db_session):
    rid, _r = _runner(client, db_session, "goal1@test.cz")
    assert client.get(f"/api/runners/{rid}/goal").json()["goal"] is None
    day = (E.today_date() + timedelta(days=200)).isoformat()
    body = {"kind": "race", "name": "Pražský maraton", "date": day, "km": 42.2, "aim": "finish"}
    pv = client.post(f"/api/runners/{rid}/goal/preview", json=body).json()
    assert pv["verdict"] in ("ok", "tight", "no") and pv["requirements"][0]["key"] == "week"
    assert pv["sourceInfo"]["toresdahl-et-al-2021"]["cite"] == "Toresdahl et al. (2021)"
    assert client.get(f"/api/runners/{rid}/goal").json()["goal"] is None          # a preview stores nothing
    saved = client.put(f"/api/runners/{rid}/goal", json=body).json()
    assert saved["goal"]["name"] == "Pražský maraton" and saved["result"]["verdict"] == pv["verdict"]
    got = client.get(f"/api/runners/{rid}/goal").json()
    assert got["goal"]["km"] == 42.2 and got["result"]["computedOn"] == E.today_date().isoformat()
    assert client.put(f"/api/runners/{rid}/goal", json={**body, "date": E.today_date().isoformat()}).status_code == 422
    assert client.put(f"/api/runners/{rid}/goal", json={"kind": "free", "date": day, "free": {}}).status_code == 422
    client.put(f"/api/runners/{rid}/goal", json={"kind": "free", "date": day, "free": {"weekly_km": 40}})
    from app import models
    assert db_session.query(models.Goal).filter(models.Goal.runner_id == rid, models.Goal.status == "active").count() == 1
    assert client.delete(f"/api/runners/{rid}/goal").json()["goal"] is None
    assert client.get(f"/api/runners/{rid}/goal").json()["goal"] is None
