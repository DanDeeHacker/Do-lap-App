"""Feedback 2026-09-29 (second round): the exercise detail content, the core and
running-drill programs, the pain regions by recency (railway#133) and an approximate
per-item share for every signal source (railway#132)."""
from app import models
from app import programs_library as PL
from app.metrics import engine as E
from app.metrics import signal_sources as SRC
from .conftest import register


def test_every_exercise_has_steps_and_faults_in_own_words():
    for k, e in PL.EXERCISES.items():
        assert 2 <= len(e["steps"]) <= 5 and e["mistakes"], k
        assert all(s.endswith(".") for s in e["steps"] + e["mistakes"]), k
        assert "—" not in " ".join(e["steps"]) and ";" not in " ".join(e["steps"]), k


def test_core_and_drill_programs_are_cited_and_marked_as_practice_where_unproven():
    core, drills = PL.PROGRAM_BY_KEY["core"], PL.PROGRAM_BY_KEY["drills"]
    assert core["group"] == drills["group"] == "performance" and not core["match"] and not drills["match"]
    assert {"plank", "side_plank", "dead_bug", "bird_dog"} <= set(core["exercises"])
    assert {"a_skip", "b_skip", "heel_flicks", "bounding", "strides"} <= set(drills["exercises"])
    assert "doloženo není" in drills["evidence"] and "praxe" in drills["assumption"]
    # performance programs are never recommended by pain
    assert not {"core", "drills"} & set(PL.programs_for_regions(["Achillova šlacha", "Hýždě (gluteus)", "Lýtko (gastrocnemius)"]))
    for p in PL.PROGRAMS:
        assert p["physio"].startswith("https://www.physio-pedia.com/") and p["group"] in ("pain", "performance")


def test_library_links_each_exercise_to_its_programs_physiopedia_pages():
    lib = PL.library()
    assert {lk["url"] for lk in lib["exercises"]["bridge"]["links"]} >= {PL.PROGRAM_BY_KEY["core"]["physio"], PL.PROGRAM_BY_KEY["knee"]["physio"]}
    assert lib["exercises"]["strides"]["links"] == [{"url": PL.PROGRAM_BY_KEY["drills"]["physio"], "topic": "Běžecká abeceda"}]
    assert all(lib["exercises"][k]["links"] for k in PL.EXERCISES)        # every exercise belongs to a program


def test_pain_regions_come_most_recent_first(client, db_session):
    rid = register(client, "fb0929b-r@test.cz", "Reg", "runner").json()["runner_id"]
    db_session.add_all([
        models.Checkin(runner_id=rid, submitted_at=E.day_ago(10), pain_score=3, pain_points=[{"region": "Achillova šlacha"}]),
        models.Checkin(runner_id=rid, submitted_at=E.day_ago(8), pain_score=3, pain_points=[{"region": "Achillova šlacha"}]),
        models.Checkin(runner_id=rid, submitted_at=E.day_ago(1), pain_score=2, pain_points=[{"region": "Úpon plantární fascie (pata)"}]),
    ])
    db_session.commit()
    d = client.get(f"/api/runners/{rid}/self-programs").json()
    assert d["regions"] == ["Úpon plantární fascie (pata)", "Achillova šlacha"]
    assert d["recommended"][0] == "achilles"               # the recommendation still follows how often


def test_approximate_shares_split_by_weight_or_equally():
    src = [{"share": None, "_w": 6}, {"share": None, "_w": 2}]
    assert SRC.split_shares("pain", src) == "pain" and [x["share"] for x in src] == [0.75, 0.25]
    assert all("_w" not in x for x in src)
    cnt = [{"share": None, "_w": 6}, {"share": None, "_w": 2}]
    assert SRC.split_shares("complaints", cnt) == "count" and [x["share"] for x in cnt] == [0.5, 0.5]
    flat = [{"share": None, "_w": 0.0}, {"share": None, "_w": 0.0}]
    assert SRC.split_shares("hrv", flat) == "equal"
    own = [{"share": 1.0, "_w": None}]
    assert SRC.split_shares("cap_volume", own) is None and own == [{"share": 1.0}]
    assert SRC.split_shares("pain", []) is None


def test_pain_signal_sources_carry_shares_and_a_note(client, db_session):
    rid = register(client, "fb0929b-s@test.cz", "Src", "runner").json()["runner_id"]
    for k, score in ((0, 6), (2, 3), (5, 2)):
        db_session.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(k), pain_score=score,
                                      pain_points=[{"region": "Achillova šlacha", "side": "left"}]))
    db_session.commit()
    a = E.recompute_assessment(db_session, rid)
    for s in a["signals"]:
        if s.get("sources"):
            assert abs(sum(x["share"] for x in s["sources"]) - 1) <= 0.02, s["id"]
            assert all("_w" not in x for x in s["sources"])
    pain = [s for s in a["signals"] if s["id"] in SRC.PAIN_DAYS and s.get("sources")]
    assert pain and all(s["shareNote"] for s in pain)


def test_recovery_carries_nights_history_and_spread_for_the_readiness_detail(client, db_session):
    """railway#138 — HRV, resting HR and sleep night by night (live only) plus the baseline
    spread for the usual-range band of each chart."""
    rid = register(client, "fb0929b-rcv@test.cz", "Rcv", "runner").json()["runner_id"]
    for k in range(0, 50):
        db_session.add(models.DailyMetric(runner_id=rid, date=E.day_ago(k)[:10], hrv_ms=60 + (k % 5), resting_hr=48 + (k % 3),
                                          sleep_h=7 + (k % 4) * 0.25))
    db_session.commit()
    r = E.recovery(db_session, rid)
    h = r["history"]
    assert 45 <= len(h) <= E.RECOVERY_HISTORY_DAYS and h == sorted(h, key=lambda x: x["d"])
    assert {"d", "hrv", "rhr", "sleep"} <= set(h[-1])
    assert r["hrv"]["sd"] > 0 and r["rhr"]["sd"] > 0 and r["sleep"]["sd"] > 0
    with E.today_pinned(E.today_date()):
        assert "history" not in E.recovery(db_session, rid)
