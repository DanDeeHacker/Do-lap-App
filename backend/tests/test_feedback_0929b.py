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


def test_displayed_scores_vary_inside_the_tier_band():
    """v0.9.2 — no fixed Skóre 60 floor: a raised tier is placed in its band by the
    trigger's severity and the model; ordinary days spread over the ok band."""
    ok = [E.display_scores(m, 0, "ok", "ok", [])["overall"] for m in (0, 3, 8, 15, 30)]
    assert ok == sorted(ok) and ok[0] == 0 and ok[-1] <= 39 and len(set(ok)) == 5 and ok[2] >= 15
    mild = E.display_scores(8, 0, "watch", "ok", [("watch", 0.125, "painRecurring")])
    bad = E.display_scores(8, 0, "watch", "ok", [("watch", 0.75, "painRecurring")])
    assert 40 <= mild["overall"] < bad["overall"] <= 69 and bad["band"]["by"] == "painRecurring"
    # a tier the model reached itself shows the model value, continuous at the cut-off
    assert E.display_scores(45, 0, "watch", "ok", [])["overall"] == 45
    assert E.display_scores(39.9, 0, "ok", "ok", [])["overall"] == 39
    # a rule lifts the symptom axis into its band by the rule's severity
    lo = E.display_scores(3, 5, "watch", "watch", [("watch", 0.2, "rule")])["symp"]
    hi = E.display_scores(3, 5, "watch", "watch", [("watch", 0.9, "rule")])["symp"]
    assert 40 <= lo < hi <= 69
    # an alert band stays at 70 or above, never below the model
    assert 70 <= E.display_scores(50, 30, "alert", "alert", [("alert", 0.3, "rule")])["overall"] <= 100


def _ci(db, rid, days_ago, pain, region="Koleno", side="L"):
    db.add(models.Checkin(runner_id=rid, submitted_at=E.day_ago(days_ago), pain_score=pain,
                          pain_points=[{"region": region, "side": side}] if pain else []))


def test_pain_episode_clean_days_halve_then_end(client, db_session):
    """v0.9.3 (owner rule) — a day that doesn't mark the site halves its level, the 2nd
    halves it again, the 3rd ends the episode."""
    rid = register(client, "ep-clean@test.cz", "Ep", "runner").json()["runner_id"]
    _ci(db_session, rid, 3, 3); _ci(db_session, rid, 2, 0); _ci(db_session, rid, 1, 0)
    db_session.commit()
    ep = next(iter(E.pain_episodes(db_session, rid).values()))
    assert ep["clean"] == 2 and abs(ep["level"] - 0.25 * 0.5 ** (1 / E.SYMP_HALF_LIFE)) < 0.002
    _ci(db_session, rid, 0, 0)
    db_session.commit()
    assert next(iter(E.pain_episodes(db_session, rid).values()))["level"] == 0


def test_pain_episode_re_marks_are_graduated_by_the_sites_median_and_p75(client, db_session):
    """Below the median of the earlier marks nothing changes, median–P75 lifts the level
    halfway back to full, above P75 it resets to full."""
    rid = register(client, "ep-grad@test.cz", "Ep", "runner").json()["runner_id"]
    for d, pain in ((6, 5), (5, 0), (4, 2), (3, 5), (2, 0), (1, 3), (0, 5)):
        _ci(db_session, rid, d, pain)
    db_session.commit()
    ep = next(iter(E.pain_episodes(db_session, rid).values()))
    # 5 → 1 · clean → ½ · 2 < median 5: kept ½ · 5 > P75 4,25: reset 1 · clean → ½ ·
    # 3 < median 5: kept ½ · 5 within median 4 … P75 5: half lift → ¾
    assert ep["how"] == "partial" and ep["level"] == 0.75 and ep["ref"] == 5 and ep["days"] == 5


def test_repeated_marks_do_not_raise_the_points(client, db_session):
    """Marking the same mild spot on more days keeps its points (until an injury report)."""
    pts = []
    for n in (3, 8):             # recurring from 3 marked days (without a set sex)
        rid = register(client, f"ep-rep{n}@test.cz", "Ep", "runner").json()["runner_id"]
        for d in range(n):
            _ci(db_session, rid, d, 2, region="Achillova šlacha", side="P")
        db_session.commit()
        a = E.recompute_assessment(db_session, rid)
        pts.append(next(s["pts"] for s in a["signals"] if s["id"] == "niggle"))
        assert a["painRecurring"]["level"] == 1.0
    assert pts[0] == pts[1] == 18
