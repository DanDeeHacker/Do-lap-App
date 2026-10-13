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
    assert tr["long"]["need"] == 21 and tr["descentRun"]["need"] == 900 and tr["descentWeek"]["need"] == 900   # finish: 0.6 × H
    tt = G.requirements(_race(30, "2027-06-01", ascentM=1500, aim="time"))
    assert tt["descentWeek"]["need"] == 1500 and tt["ascentWeek"]["need"] == 1500                             # a target time: × 1
    assert tr["descSessions"]["need"] == 10
    flat = 30 + 7.92 * 1.5                                               # Scarf: climb as flat km
    assert tr["week"]["need"] >= max(45.0, G._interp(flat, 0, 0)) - 0.01
    # ultra (owner report: 101 km / 5 500 m asked for 152 km a week): capped at what ultra runners train
    u = G.requirements(_race(101, "2027-08-28", ascentM=5500))
    assert u["week"]["need"] == 70 and u["long"]["need"] == 35
    assert abs(u["ascentRun"]["need"] - 5500 / 101 * 35) < 1 and u["ascentWeek"]["need"] == 0.6 * 5500
    assert "hoffman-and-krishnan-2014" in u["week"]["sources"]
    ut = G.requirements(_race(101, "2027-08-28", ascentM=5500, aim="time"))
    assert ut["week"]["need"] == 90 and ut["long"]["need"] == 45


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


# ------------------------------------------------------------------ stage 2: the plan towards the goal
def test_plan_weeks_phases_taper_and_milestone():
    st = {**_st(), "start": "2026-10-12", "cyclePos": 2}
    r = G.evaluate(_race(42.2, "2027-05-02"), st)
    plan = r["plan"]
    assert len(plan) == r["weeksToGoal"] and plan[0]["start"] == "2026-10-12"
    phases = [w["phase"] for w in plan]
    assert phases[-2:] == ["taper", "taper"] and plan[-1]["race"]                     # 2 weeks for the marathon
    order = ["base", "build", "specific", "taper"]
    assert [order.index(p) for p in phases] == sorted(order.index(p) for p in phases)  # phases never go back
    assert [w["factor"] for w in plan[-2:]] == G.TAPER["M"]
    peak = max(w["km"] for w in plan[-6:-2] if not w["deload"])
    assert abs(plan[-1]["km"] - 0.40 * peak) < 0.2
    assert all(w["deload"] == ((2 - 1 + w["i"] - 1) % 4 == 3) for w in plan if w["phase"] != "taper")   # the app's cycle goes on
    assert sum(1 for w in plan if w.get("milestone") == "half") == 1                   # first marathon, no half yet
    assert all(w.get("runs") == 3 for w in plan)
    for w in plan:
        if w["phase"] in ("base", "build") and w.get("long"):
            assert w["long"] <= max(0.3 * w["km"], 12.0) + 0.11                        # 30 % before the specific phase
        if w["phase"] == "specific" and w.get("long"):
            assert w["long"] <= 0.5 * w["km"] + 0.11
    assert G.taper_factors(_race(10, "2027-01-01")) == [0.55]
    assert G.taper_factors(_race(21.1, "2027-01-01")) == [0.65, 0.45]


def _goal_runner(client, db_session, email):
    rid, r = _runner(client, db_session, email)
    day = (E.today_date() + timedelta(days=7 * 26)).isoformat()
    res = client.put(f"/api/runners/{rid}/goal", json={"kind": "race", "name": "Maraton", "date": day, "km": 42.2})
    assert res.status_code == 200, res.text
    return rid, res.json()


def test_guidance_follows_the_goal_plan(client, db_session):
    rid, saved = _goal_runner(client, db_session, "goal2@test.cz")
    a = E.get_or_refresh_assessment(db_session, rid)
    g = a["guidance"]
    assert g["week"]["mode"] in ("goal", "deload")
    go = g["goal"]
    assert go and go["week"]["i"] == 1 and go["weeks"] == len(saved["result"]["plan"])
    from app.metrics import week_plan as WP
    wp = WP.build(a, E.today_date())
    if g["week"]["mode"] == "goal" and wp:
        assert wp["headline"].startswith("Plán k cíli")
    if g["week"]["mode"] == "goal":
        v = g["week"]["channels"]["volume"]
        assert v["budget"] <= go["week"]["km"] + 0.11                    # never over the plan …
        assert v["ceiling7"] is None or v["budget"] <= v["ceiling7"] + 0.11   # … nor over the weekly ceiling
        assert any("Plán k cíli" in x for x in g["reasons"])
    assert client.delete(f"/api/runners/{rid}/goal").status_code == 200
    assert (E.get_or_refresh_assessment(db_session, rid)["guidance"]["week"]["mode"]) != "goal"


def test_a_goal_not_even_the_risk_path_reaches_is_refused(client, db_session):
    rid, _r = _runner(client, db_session, "goal3@test.cz")
    day = (E.today_date() + timedelta(days=21)).isoformat()
    res = client.put(f"/api/runners/{rid}/goal", json={"kind": "race", "date": day, "km": 42.2, "aim": "time"})
    assert res.status_code == 422 and "riziková cesta" in res.json()["detail"]


# ------------------------------------------------------------------ stage 3: the risk path
def test_risk_path_needs_consent_widens_the_limits_and_ends_on_pain(client, db_session):
    from app import models
    rid, saved = _goal_runner(client, db_session, "goal4@test.cz")
    assert client.put(f"/api/runners/{rid}/goal/path", json={"path": "risk"}).status_code == 422   # no consent
    safe = E.get_or_refresh_assessment(db_session, rid)["guidance"]
    if not saved["result"].get("riskPossible"):
        return
    r = client.put(f"/api/runners/{rid}/goal/path", json={"path": "risk", "consent": True})
    assert r.status_code == 200 and r.json()["goal"]["path"] == "risk"
    g = E.get_or_refresh_assessment(db_session, rid)["guidance"]
    assert g["goal"]["path"] == "risk"
    sv, rv = safe["week"]["channels"]["volume"], g["week"]["channels"]["volume"]
    if sv.get("ceilingRun") and rv.get("ceilingRun") and g["week"]["mode"] == "goal":
        assert rv["ceilingRun"] > sv["ceilingRun"]                          # +15 % instead of +10 % per run
        so, ro = safe["outlook"]["channels"]["volume"]["byNight"]["good"], g["outlook"]["channels"]["volume"]["byNight"]["good"]
        assert ro["run"] > so["run"]                                        # tomorrow's outlook widened the same way
    row = db_session.query(models.Goal).filter(models.Goal.runner_id == rid, models.Goal.status == "active").first()
    assert row.risk_consent_at
    db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=4, pain_points=[{"region": "koleno"}]))
    db_session.commit()
    a = E.recompute_assessment(db_session, rid)
    db_session.refresh(row)
    assert row.path == "safe" and "bolest" in (row.risk_end_reason or "")
    assert a["guidance"]["goal"]["path"] == "safe"
    assert G.risk_end_reason({"guidance": {"pain": 0, "planCtx": {}},
                              "capacity": {"readiness": {"known": True, "score": 60, "yesterday": {"known": True, "score": 62}}}})


# ------------------------------------------------------------------ stage 4: assistant, reports, coach, target time
def test_assistant_and_reports_know_the_goal(client, db_session):
    from app.assistant import facts as FA, selector as SEL, service as S
    from app.metrics import daily_report as DR
    rid, _saved = _goal_runner(client, db_session, "goal5@test.cz")
    sel = SEL.classify("Stihnu ten maraton v termínu?")
    assert "goal" in sel["intents"] and "goal" in sel["slices"]
    a = E.get_or_refresh_assessment(db_session, rid)
    f = FA.build(db_session, rid, a, sel)
    gl = f["goal"]
    assert gl["verdict"] and gl["thisWeek"]["km"] and any("Toresdahl et al. (2021)" in r for r in gl["requirements"])
    txt = S.fallback_answer(sel, f, [], [])
    assert "Cíl" in txt and "Tento týden plánu" in txt
    m = DR.build(db_session, rid, "morning")
    assert m["goal"] and "Do cíle" in m["goal"]["text"]
    assert DR.build(db_session, rid, "evening")["goal"]


def test_target_time_and_the_coach_check(client, db_session):
    t = G.target_time({"aim": "time", "km": 42.2, "targetTimeS": 4 * 3600}, 4 * 3600 * 1.1, None)
    assert t["paceText"] == "5:41 /km" and t["gapPct"] == 10.0 and "ambiciózní" in t["text"]
    assert G.target_time({"aim": "finish", "km": 42.2, "targetTimeS": 4 * 3600}, None, None) is None
    from app import models
    rid, _saved = _goal_runner(client, db_session, "goal6@test.cz")
    client.put(f"/api/runners/{rid}/plan/mode", json={"on": True})
    d = (E.today_date() + timedelta(days=3)).isoformat()
    db_session.add(models.PlannedSession(runner_id=rid, date=d, seq=0, kind="long", title="Dlouhý", km=18, source="manual"))
    db_session.commit()
    g = E.recompute_assessment(db_session, rid)["guidance"]
    assert g["week"]["mode"] == "coach"
    cc = g["goal"]["coachCheck"]
    assert cc and not cc["ok"] and "nejdelší běh v plánu 18" in cc["text"]
    r = client.put(f"/api/runners/{rid}/goal", json={"kind": "race", "date": (E.today_date() + timedelta(days=200)).isoformat(),
                                                     "km": 21.1, "aim": "time", "target_time_s": 6000})
    assert r.json()["result"]["targetTime"]["paceText"]


def test_a_goal_this_week_is_the_race_week_of_the_taper():
    st = {**_st(), "start": "2026-10-12"}
    plan = G.evaluate(_race(21.1, "2026-10-18"), st)["plan"]
    assert len(plan) == 1 and plan[0]["race"] and plan[0]["factor"] == G.TAPER[2][-1]


def test_a_narrow_margin_grows_slower_but_never_shrinks():
    """Owner report 2026-10-12: with a weekly margin under ~11 % the planned recovery weeks pulled
    the projected capacity down week after week, so a trail goal was "not within 2 years"."""
    for mw in (0.15, 0.10, 0.06):
        st = {**_st(km=30.0, long=21.0, climb=250.0), "marginWeek": mw, "marginWhy": ["dřívější zranění"]}
        req = G.requirements(_race(33.3, "2026-11-28", ascentM=1300))
        p = G.project(req, st, G.SAFE, 1, until=60)
        loaded = [r["km"] for r in p["rows"] if not r["deload"]]
        assert all(b >= a - 0.11 for a, b in zip(loaded, loaded[1:])), mw      # the build weeks never go down
        assert p["firstMet"]["week"] is not None, mw                             # 55 km a week is reached
        asc = [r["ascent"] for r in p["rows"] if not r["deload"]]
        assert all(b >= a - 0.6 for a, b in zip(asc, asc[1:])), mw
    r = G.evaluate(_race(33.3, "2026-11-28", ascentM=1300), {**_st(km=30.0, long=21.0, climb=250.0), "marginWeek": 0.06,
                                                             "marginWhy": ["dřívější zranění"]})
    assert any(n["key"] == "margin" and "6 % místo 15 %" in n["text"] and "dřívější zranění" in n["text"] for n in r["notes"])
    assert "do 2 let" not in r["text"]


def test_after_lighter_weeks_the_plan_climbs_back_as_fast_as_the_app_allows():
    """Owner report 2026-10-13: 50 km weeks in September, then lighter ones — the plan started at
    19 km, less than Trénink gives without a goal. The rise counts from the capacity the app
    credits, not only from the last 2 weeks."""
    km = [50.0, 52.0, 45.0, 28.0, 20.0, 17.0]
    st = {**_st(), "weeks": [{**w, "km": k, "down": 0.0, "up": 0.0} for w, k in zip(_st()["weeks"], km)],
          "marginWeek": 0.12, "cyclePos": 1}
    p = G.project(G.requirements(_race(42.2, "2027-05-01")), st, G.SAFE, 1, until=30)
    ceil = G._cap(km) * 1.12
    assert abs(p["rows"][0]["km"] - min(ceil, 1.5 * sum(km[-4:]) / 4)) < 0.11          # the app's own weekly ceiling
    assert p["rows"][0]["km"] > max(km[-2:]) * 1.15 + 5                                 # not 15 % over the light weeks


def test_per_run_capacity_remembers_90_days_like_the_engine(client, db_session):
    """A long, steep run 60 days before Monday still counts half (30-day half-life after 30 days),
    as in capacity.session_capacity — before, the plan only knew the last 30 days."""
    from app import models
    from .conftest import register
    rid = register(client, "goalmem@test.cz", "Mem Runner", "runner").json()["runner_id"]
    mon = E.today_date() - timedelta(days=E.today_date().weekday())
    for i, (ago, km, desc) in enumerate([(60, 24.0, 900.0), (10, 8.0, 100.0), (8, 8.0, 100.0), (5, 8.0, 100.0)]):
        db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"mem-{i}", sport="running",
                                       started_at=(mon - timedelta(days=ago)).isoformat() + "T07:00:00",
                                       title="Běh", distance_km=km, duration_min=km * 6, ascent_m=desc, descent_m=desc))
    db_session.commit()
    st = G.runner_state(db_session, rid, {})
    from app.metrics import capacity as C
    # the descent in the engine's weighted metres (no profile → the default steepness factor)
    assert abs(st["long30"] - 24.0 * 0.5) < 0.05 and abs(st["down30"] - 900.0 * C.ECC_DEFAULT * 0.5) < 0.5


def test_the_plan_remembers_the_former_level_like_the_engine():
    """v0.12.6 (owner decision 2026-10-13): 50 km weeks until 7 weeks ago, 20 km since — the
    projection gets the engine's former level (≤ 1.3 / 1.15 × the 4-week average), so the way
    back grows ~10 % a week instead of the usual few per cent."""
    from app.metrics import capacity as C
    km = [50.0] * 6 + [20.0] * 6
    assert G._cap(km) == C.RETURN_ACWR / (1 + C.MARGIN_WEEK) * 20
    assert G._cap([20.0] * 12) == 20.0
    w = [{"km": k, "long": 10.0, "down": 0.0, "up": 0.0, "downRun": 0.0, "upRun": 0.0, "runs": 4} for k in km]
    back = {**_st(), "weeks": w, "cyclePos": 1}
    flat = {**_st(), "weeks": [{**x, "km": 20.0} for x in w], "cyclePos": 1}
    req = G.requirements(_race(42.2, "2027-05-01"))
    pb, pf = G.project(req, back, G.SAFE, 1, until=12), G.project(req, flat, G.SAFE, 1, until=12)
    assert pb["rows"][2]["km"] > pf["rows"][2]["km"] * 1.1                     # faster back to the former level
    assert all(r["km"] <= 1.3 * 1.15 * 50 for r in pb["rows"])


def test_a_goal_not_safe_by_its_date_gets_the_best_safe_goal():
    """Owner request 2026-10-13: when the goal isn't safe by its date, the app offers the largest one
    of the same kind that is (safe path, taper and reserve), at the edge and still a step up."""
    st = {**_st(km=20.0, long=10.0, climb=200.0), "start": "2026-10-12", "cyclePos": 1}
    for goal in (_race(101, "2027-08-28", ascentM=5500, descentM=5500, terrain="trail"), _race(42.2, "2026-12-20"),
                 {"kind": "free", "date": "2027-01-31", "free": {"weeklyKm": 60, "longKm": 30, "climbM": 1500, "climbScope": "week"}}):
        r = G.evaluate(goal, st)
        assert r["verdict"] != "ok"
        b = r["alternatives"][0]
        assert b["kind"] == "best" and b["verdict"] == "ok" and "posune vás" in b["text"], goal
        g = b["goal"]
        assert G.evaluate(g, st, alternatives=False)["verdict"] == "ok"
        if goal.get("kind") != "free":                                   # the next size up is not safe any more
            steps = G.TRAIL_STEPS if G.is_trail(goal) else G.ROAD_STEPS
            bigger = [d for d in steps if g["km"] + 0.5 < d < goal["km"] - 0.5]
            if bigger:
                k = bigger[0]
                g2 = dict(g, km=float(k), **({"ascentM": round(5500 * k / 101 / 50) * 50, "descentM": round(5500 * k / 101 / 50) * 50}
                                             if G.is_trail(goal) else {}))
                assert G.evaluate(g2, st, alternatives=False)["verdict"] != "ok"
        else:
            assert g["free"]["weeklyKm"] > 20                               # a step up from today's 20 km
    trail = G.evaluate(_race(101, "2027-08-28", ascentM=5500, descentM=5500, terrain="trail"), st)["alternatives"][0]["goal"]
    assert abs(trail["ascentM"] / trail["km"] - 5500 / 101) < 3             # the same climb per km
    assert G.evaluate(_race(10, "2027-08-28"), st).get("alternatives") is None   # a safe goal needs none


def test_descent_sessions_already_done_count():
    """Owner report 2026-10-13: hilly weeks of the last 12 count towards the 10 descent sessions
    (the repeated bout effect lasts ≥ 6 months, Nosaka 2001); a short trail's sessions can count."""
    req = G.requirements(_race(33.3, "2027-03-01", ascentM=1300, descentM=1300))
    st = _st(km=40.0, long=18.0, climb=900.0)                         # downRun 450 m every week
    assert G.desc_done(req, st) == 10
    flat = _st(km=40.0, long=18.0, climb=100.0)
    assert G.desc_done(req, flat) == 0
    short = G.requirements(_race(5, "2027-03-01", ascentM=200, descentM=200, terrain="trail"))
    assert G._desc_min(short) <= short["descentRun"]["need"]
    assert G.project(short, {**flat, "cyclePos": 1}, G.SAFE, 1, until=30)["readyWeek"] is not None


def test_the_answer_carries_what_the_gauges_draw():
    """Owner feedback 2026-10-13 (pictures, not sentences): each requirement says where the safe path
    stands at the start and the week it is met; the best goal lists its steps; a free 100 km long run
    no longer asks for a 200 km week."""
    st = {**_st(km=20.0, long=10.0, climb=200.0), "start": "2026-10-12", "cyclePos": 1}
    r = G.evaluate(_race(42.2, "2027-06-27"), st)
    week = next(q for q in r["requirements"] if q["key"] == "week")
    assert week["atRace"] is not None and (week["metWeek"] is None or week["metWeek"] >= 1)
    free = G.evaluate({"kind": "free", "date": "2028-05-13", "free": {"weeklyKm": 30, "longKm": 100, "climbM": 3000, "climbScope": "run"}}, st)
    assert next(q for q in free["requirements"] if q["key"] == "week")["need"] <= G.ULTRA_WEEK["time"]
    assert any(n["key"] == "ultra" for n in free["notes"])
    b = next(a for a in free.get("alternatives") or [] if a["kind"] == "best")
    need = {q["key"]: q["need"] for q in G.evaluate(b["goal"], st, alternatives=False)["requirements"]}
    assert b["goal"]["free"]["weeklyKm"] == round(need["week"]) and b["progress"]          # the label says what it asks


def test_the_plan_and_the_engine_agree_on_the_weekly_ceiling(client, db_session):
    """Plan k cíli 2.0 #1: the plan's ceiling for this week is the engine's own weekly capacity ×
    (1 + margin) — the projection runs capacity.weekly_capacity_vals on the same days. 20 runners
    of different volumes and gaps; at most 3 % apart."""
    import random
    from app import models
    from app.metrics import capacity as C
    from .conftest import register
    rng = random.Random(7)
    today = E.today_date()
    mon = today - timedelta(days=today.weekday())
    for k in range(20):
        rid = register(client, f"agree{k}@test.cz", "Agree Runner", "runner").json()["runner_id"]
        base = rng.uniform(15, 70)
        for d in range(1, 120):
            day = mon - timedelta(days=d)
            if rng.random() < 0.55 and not (k % 4 == 0 and 30 < d < 45):          # some runners had a break
                km = base / 4 * rng.uniform(0.6, 1.5)
                db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"ag{k}-{d}", sport="running",
                                               started_at=day.isoformat() + "T07:00:00", title="Běh", distance_km=km,
                                               duration_min=km * 6, ascent_m=km * 10, descent_m=km * 10))
        db_session.commit()
        st = G.runner_state(db_session, rid, {})
        pain = C.pain_dates(db_session, rid)
        daily = {}
        for a in E.acts(db_session, rid, "load"):
            daily[a.started_at[:10]] = daily.get(a.started_at[:10], 0.0) + a.distance_km
        first = min(daily)
        engine = C.weekly_capacity(daily, (mon + timedelta(days=6)).isoformat(), first, pain, "volume")
        plan = G._engine_cap(st["days"]["km"], st["pain"], st["known"], "volume")
        assert abs(plan - engine) <= 0.03 * engine, (k, plan, engine)


def test_a_gap_without_watch_data_is_asked_once(client, db_session):
    """Plan k cíli 2.0 #4: 4 days without any reading or activity → the question; "rest" keeps it away;
    a run logged by hand fills a day."""
    from app import models
    from .conftest import register
    rid = register(client, "gap@test.cz", "Gap Runner", "runner").json()["runner_id"]
    today = E.today_date()
    for k in range(1, 40):
        d = (today - timedelta(days=k)).isoformat()
        if 3 <= k <= 6:
            continue                                                        # the watch stayed at home
        db_session.add(models.DailyMetric(runner_id=rid, date=d, resting_hr=50, hrv_ms=60, sleep_h=7.5))
    db_session.commit()
    gap = client.get(f"/api/runners/{rid}/gaps").json()["gap"]
    assert gap == {"from": (today - timedelta(days=6)).isoformat(), "to": (today - timedelta(days=3)).isoformat(), "days": 4}
    r = client.post(f"/api/runners/{rid}/activities/manual", json={"sport": "running", "date": gap["to"], "distance_km": 8,
                                                                 "duration_min": 48, "rpe": 4})
    assert r.status_code == 200
    gap = client.get(f"/api/runners/{rid}/gaps").json()["gap"]
    assert gap and gap["days"] == 3                                         # the logged day is filled
    assert client.post(f"/api/runners/{rid}/gaps", json={"from": gap["from"], "to": gap["to"], "answer": "rest"}).json()["gap"] is None
    assert client.get(f"/api/runners/{rid}/gaps").json()["gap"] is None


def test_the_goal_record_adherence_checkpoints_and_setbacks(client, db_session):
    """Plan k cíli 2.0 #7–#9: the Monday snapshot, two weeks under 80 % flagged, a checkpoint due
    behind the plan, 7 days without hard sessions after an illness day and 3 after a break."""
    from types import SimpleNamespace
    from app import models
    from app.metrics import goal_track as GT
    from .conftest import register
    rid = register(client, "track@test.cz", "Track Runner", "runner").json()["runner_id"]
    today = E.today_date()
    mon = today - timedelta(days=today.weekday())
    g = models.Goal(runner_id=rid, kind="race", name="M", date=(mon + timedelta(days=7 * 20 + 6)).isoformat(), distance_km=42.2,
                    aim="finish", status="active", created_at=(mon - timedelta(days=7 * 20)).isoformat(), track_json={})
    db_session.add(g)
    for k in (1, 2):                                   # the two weeks before: 40 km planned, 20 km run
        s = mon - timedelta(days=7 * k)
        g.track_json = {**(g.track_json or {}), "weeks": {**((g.track_json or {}).get("weeks") or {}),
                        s.isoformat(): {"km": 40.0, "long": 16.0, "strength": 2}}}
        for d in (1, 3):
            db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id=f"tr{k}{d}", sport="running",
                                           started_at=(s + timedelta(days=d)).isoformat() + "T07:00:00", distance_km=10.0, duration_min=60))
    db_session.commit()
    ad = GT.adherence(db_session, rid, g, today)
    assert [w["pct"] for w in ad["weeks"]] == [50, 50] and ad["flag"] == "under" and ad["strengthPct"] == 0
    assert GT.snapshot(g, {"week": {"km": 30.0, "long": 12.0, "strength": 2}, "realDate": "2027-06-01", "status": "behind"}, today)
    assert not GT.snapshot(g, {"week": {"km": 31.0}, "realDate": "2027-06-08"}, today)          # once a week
    assert GT.setback(g, {"realDate": "2027-06-15"}, today) == {"from": "2027-06-01", "to": "2027-06-15", "days": 14}
    cp = GT.checkpoint(g, {"status": "behind"}, today)
    assert cp and cp["behind"] and cp["key"] == "half"
    GT.answer_checkpoint(g, cp["key"], today)
    assert GT.checkpoint(g, {"status": "behind"}, today) is None
    g.track_json = {**g.track_json, "illLast": (today - timedelta(days=2)).isoformat()}
    assert GT.returning(g, [], today)["why"] == "nemoc"
    g.track_json = {**g.track_json, "illLast": None}
    runs = [(today - timedelta(days=k)).isoformat() for k in (12, 11, 1)]                    # a 10-day break, back yesterday
    assert GT.returning(g, runs, today)["why"] == "pauza"
    assert GT.returning(g, [(today - timedelta(days=k)).isoformat() for k in (3, 2, 1)], today) is None


def test_strength_is_a_fixed_part_of_the_plan(client, db_session):
    """Plan k cíli 2.0 #14: 2× in base and build, 1× in the specific phase and the taper, none in
    the race week; Trénink schedules what the plan says."""
    res = G.evaluate(_race(42.2, "2027-04-25"), _st(km=40, long=18))
    plan = res["plan"]
    for w in plan:
        want = 0 if w.get("race") else 1 if (w.get("taper") or w.get("deload") or w["phase"] == "specific") else 2
        assert w["strength"] == want, w
    assert {w["strength"] for w in plan} == {0, 1, 2}
    rid, _saved = _goal_runner(client, db_session, "goalstr@test.cz")
    g = E.get_or_refresh_assessment(db_session, rid)["guidance"]
    if g["week"]["mode"] == "goal":
        assert g["strength"]["target"] == g["goal"]["week"]["strength"]
        assert any("chodidla" in n for n in g["types"]["posilování"]["notes"])


def test_the_energy_and_bone_screen(client, db_session):
    """Plan k cíli 2.0 #17: offered for a long plan, a past bone stress injury narrows the margins
    and adds a reserve week, a missing period (answer or the cycle log) stops the growth."""
    from types import SimpleNamespace
    from app.metrics import energy as EN
    today = E.today_date()
    log = {"track": True, "hormonal": False, "starts": [(today - timedelta(days=d)).isoformat() for d in (150, 122, 95)]}
    she = SimpleNamespace(sex="female", menstrual_json=log, planner_json=None)
    assert EN.state(she, today)["hold"]["auto"]                         # 95 days since the last period
    she.menstrual_json = {**log, "starts": log["starts"] + [(today - timedelta(days=10)).isoformat()]}
    assert EN.state(she, today)["hold"] is None
    she.menstrual_json = {**log, "hormonal": True}
    assert EN.state(she, today)["hold"] is None                         # the pill: the log says nothing
    assert EN.ask(she, {"weeksToGoal": 20, "plan": []}) and not EN.ask(she, {"weeksToGoal": 8, "plan": [{"km": 30}]})

    rid, saved = _goal_runner(client, db_session, "goalen@test.cz")
    got = client.get(f"/api/runners/{rid}/goal").json()
    assert got["energy"]["ask"]                                          # a 26-week plan
    before = got["result"]
    after = client.post(f"/api/runners/{rid}/goal/energy", json={"bsi": True}).json()
    assert not after["energy"]["ask"] and after["energy"]["bsi"]
    assert after["result"]["margins"]["week"] < before["margins"]["week"]
    assert after["result"]["reserveWeeks"] == before["reserveWeeks"] + 1
    assert any(n["key"] == "margin" and "dřívější únavová zlomenina" in n["why"] for n in after["result"]["notes"])
    held = client.post(f"/api/runners/{rid}/goal/energy", json={"period": True}).json()
    assert held["result"]["hold"]["kind"] == "energy" and held["result"]["notes"][0]["key"] == "energy"
    g = E.get_or_refresh_assessment(db_session, rid)["guidance"]
    if g["week"]["mode"] == "goal":
        assert g["goal"]["hold"] and any("neroste" in x for x in g["reasons"])
    assert client.post(f"/api/runners/{rid}/goal/energy", json={"declined": True}).json()["energy"]["declined"]


def test_the_goal_outcome_is_asked_after_its_date(client, db_session):
    """Plan k cíli 2.0 #19: after the date, started / finished / time, with the preparation's record."""
    from app import models
    from .conftest import register
    rid = register(client, "outcome@test.cz", "Outcome Runner", "runner").json()["runner_id"]
    today = E.today_date()
    mon = today - timedelta(days=today.weekday())
    wk = (mon - timedelta(days=14)).isoformat()
    g = models.Goal(runner_id=rid, kind="race", name="Půlmaraton", date=(today - timedelta(days=2)).isoformat(),
                    distance_km=21.1, aim="time", target_time_s=6300, status="active",
                    created_at=(today - timedelta(days=60)).isoformat(),
                    track_json={"weeks": {wk: {"km": 30.0, "long": 14.0, "strength": 2}}},
                    projection_json={"verdict": "ok", "status": "ok", "realDate": (today - timedelta(days=20)).isoformat()})
    db_session.add(g)
    db_session.add(models.Activity(runner_id=rid, provider="garmin", external_id="oc1", sport="running",
                                   started_at=wk + "T07:00:00", distance_km=24.0, duration_min=140))
    db_session.commit()
    got = client.get(f"/api/runners/{rid}/goal").json()
    assert got["goal"] is None and got["outcome"]["goalId"] == g.id and got["outcome"]["targetTimeS"] == 6300
    res = client.post(f"/api/runners/{rid}/goal/outcome",
                      json={"goal_id": g.id, "started": True, "finished": True, "time_s": 6400})
    assert res.status_code == 200 and res.json()["outcome"] is None
    db_session.refresh(g)
    o = g.outcome_json
    assert o["finished"] and o["timeS"] == 6400 and o["verdict"] == "ok" and o["kmPct"] == 80 and o["strengthPct"] == 0
    assert not o["injury"]
    assert client.post(f"/api/runners/{rid}/goal/outcome", json={"goal_id": g.id, "skipped": True}).status_code == 409
