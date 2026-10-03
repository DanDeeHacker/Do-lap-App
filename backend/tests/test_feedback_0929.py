"""Feedback railway#114–#128 (2026-09-29): the activity carousel order, swimming only,
the sleep history, race elevation / planned pace, and self-started exercise programs."""
from datetime import timedelta

from app import models
from app import programs_library as PL
from app.metrics import engine as E
from app.metrics import guidance as G
from .conftest import register
from .test_guidance import _guide, _pain, _runner


def test_carousel_rank_starts_with_the_recommendation_and_ends_with_the_blocked():
    types = {k: {"allowed": True} for k in ("volno", "regenerace", "lehký", "dlouhý", "kvalitní", "kolo", "voda", "posilování")}
    types["kvalitní"]["allowed"] = False
    r = G.rank_types(types, "lehký", strength_due=False)
    assert r[0] == "lehký" and r[-1] == "kvalitní"
    # a light day puts the low-load options ahead of the long run
    r2 = G.rank_types(types, "regenerace", strength_due=True)
    assert r2[:2] == ["regenerace", "posilování"] and r2.index("voda") < r2.index("dlouhý")
    # cycling that loads the painful spot goes after the other allowed options
    r3 = G.rank_types(types, "volno", strength_due=False, xt={"kolo": "caution"})
    assert r3.index("kolo") > r3.index("voda")


def test_guidance_carries_the_rank_and_offers_only_swimming(client, db_session):
    rid, r = _runner(client, db_session, "fb0929-g@test.cz")
    g = _guide(db_session, rid, r)
    assert g["rank"][0] == g["type"] and set(g["rank"]) == set(g["types"])
    assert g["types"]["voda"]["label"] == "Plavání"
    assert not any("běh ve vodě" in n.lower() for n in g["types"]["voda"]["notes"])
    _pain(db_session, rid, 7, region="lýtko")
    g2 = _guide(db_session, rid, r)
    assert not any("běh ve vodě" in x for x in g2["reasons"])


def test_sleep_history_for_the_chart(client, db_session):
    rid = register(client, "fb0929-s@test.cz", "Sleep", "runner").json()["runner_id"]
    for k in range(0, 70):
        db_session.add(models.DailyMetric(runner_id=rid, date=E.day_ago(k)[:10], sleep_h=7 + (k % 3) * 0.3,
                                          sleep_efficiency=0.93, deep_min=70 + k % 5, rem_min=90, light_min=250))
    db_session.commit()
    s = E.sleep_efficiency(db_session, rid)
    h = s["history"]
    assert 55 <= len(h) <= E.SLEEP_HISTORY_DAYS and h == sorted(h, key=lambda x: x["d"])
    assert {"d", "sleep", "deep", "rem"} <= set(h[-1])
    with E.today_pinned(E.today_date()):
        assert "history" not in E.sleep_efficiency(db_session, rid)       # not in the history replay


def test_race_elevation_and_planned_pace(client, db_session):
    rid = register(client, "fb0929-r@test.cz", "Racer", "runner").json()["runner_id"]
    d = (E.today_date() + timedelta(days=20)).isoformat()
    r = client.post(f"/api/runners/{rid}/races", json={"date": d, "name": "Trail", "distance_km": 22, "priority": "B",
                                                         "ascent_m": 850, "target_pace_s_km": 390})
    assert r.status_code == 200
    race = next(x for x in r.json()["races"] if x["name"] == "Trail")
    assert race["ascentM"] == 850 and race["paceSKm"] == 390
    u = client.patch(f"/api/runners/{rid}/races/{race['id']}", json={"ascent_m": 900, "target_pace_s_km": 400, "name": "Trail 22"})
    assert u.status_code == 200
    race2 = next(x for x in u.json()["races"] if x["id"] == race["id"])
    assert race2["ascentM"] == 900 and race2["paceSKm"] == 400 and race2["name"] == "Trail 22" and race2["km"] == 22
    assert client.patch(f"/api/runners/{rid}/races/{race['id']}", json={"target_pace_s_km": 30}).status_code == 422
    assert client.patch(f"/api/runners/{rid}/races/999999", json={"name": "x"}).status_code == 404


def test_programs_library_is_cited_and_matches_pain_regions():
    for p in PL.PROGRAMS:
        assert p["exercises"] and all(x in PL.EXERCISES for x in p["exercises"])
        assert p["refs"] and all(ref in PL.REFERENCES for ref in p["refs"])
        assert all(ref.split(",")[0].split(" et al")[0] in p["evidence"] for ref in p["refs"])
    assert PL.programs_for_regions(["Achillova šlacha", "Achillova šlacha", "Lýtko (gastrocnemius)"])[:2] == ["achilles", "calf"]
    assert PL.programs_for_regions(["Úpon plantární fascie (pata)"]) == ["plantar"]
    assert PL.programs_for_regions(["Iliotibiální trakt (IT band)"]) == ["itb"]
    assert PL.programs_for_regions(["Rotátorová manžeta"]) == []


def test_self_programs_recommend_start_log_and_end(client, db_session):
    rid = register(client, "fb0929-p@test.cz", "Prog", "runner").json()["runner_id"]
    db_session.add(models.Checkin(runner_id=rid, submitted_at=E.now_iso(), pain_score=3,
                                  pain_points=[{"region": "Úpon plantární fascie (pata)", "side": "left"}]))
    db_session.commit()
    d = client.get(f"/api/runners/{rid}/self-programs").json()
    assert d["recommended"] == ["plantar"] and d["active"] is None and d["library"]["programs"]
    p = client.post(f"/api/runners/{rid}/self-programs", json={"template": "plantar"}).json()
    assert p["name"] == "Plantární fascie (pata)" and p["exercises"][0]["id"] == "towel_raise"
    lg = client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": "towel_raise", "done": True}).json()
    assert lg["exercises"][0]["doneToday"] and lg["exercises"][0]["doneWeek"] == 1
    un = client.patch(f"/api/runners/{rid}/self-programs/{p['id']}/log", json={"exercise": "towel_raise", "done": False}).json()
    assert not un["exercises"][0]["doneToday"]
    # feedback #186 — an own session runs next to the program (newest first); the same template isn't doubled
    own = client.post(f"/api/runners/{rid}/self-programs", json={"name": "Moje", "exercises": ["bridge", "clamshell", "nope"]}).json()
    assert own["name"] == "Moje" and [e["id"] for e in own["exercises"]] == ["bridge", "clamshell"]
    d = client.get(f"/api/runners/{rid}/self-programs").json()
    assert d["active"]["id"] == own["id"] and [x["id"] for x in d["actives"]] == [own["id"], p["id"]]
    assert client.post(f"/api/runners/{rid}/self-programs", json={"template": "plantar"}).json()["id"] == p["id"]
    assert client.post(f"/api/runners/{rid}/self-programs", json={"exercises": []}).status_code == 422
    assert client.delete(f"/api/runners/{rid}/self-programs/{own['id']}").status_code == 200
    assert client.delete(f"/api/runners/{rid}/self-programs/{p['id']}").status_code == 200
    assert client.get(f"/api/runners/{rid}/self-programs").json()["active"] is None
