"""feedback #225 — basic running statistics as number cards (Moje čísla): the week's totals and
the last activity come from frontend/src/runstats.ts. The app has no browser test runner, so the
helper is run with Node (type stripping) and skipped where Node is too old for that."""
import json
import os
import shutil
import subprocess

import pytest

from .conftest import register

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "runstats.ts"))

PROBE = """
import { weekStats, lastActivity, hm, paceStr, recentActivities, sportCs, weeklyTotals } from %r
const acts = [
  { started_at: "2026-11-02T07:00:00", sport: "running", duration_min: 50, ascent_m: 300, descent_m: 290 },
  { started_at: "2026-11-03T18:00:00", sport: "cycling", duration_min: 70 },
  { started_at: "2026-11-03T19:00:00", sport: "running", duration_min: 30, ascent_m: 90, descent_m: 80, excluded: true },
  { started_at: "2026-10-30T07:00:00", sport: "running", duration_min: 60, ascent_m: 500, descent_m: 500 },
]
console.log(JSON.stringify({ week: weekStats(acts, "2026-11-04"), last: lastActivity(acts).started_at,
  empty: weekStats([], "2026-11-04"),
  recent: recentActivities(acts, 2).map((x) => x.started_at), all: recentActivities(acts).length, none_recent: recentActivities([]).length,
  wAll: weeklyTotals(acts, 3, "all", "2026-11-04"), wRun: weeklyTotals(acts, 3, "run", "2026-11-04"), wUp: weeklyTotals(acts, 2, "ascent", "2026-11-04"),
  sports: [sportCs("running"), sportCs(null), sportCs("cycling"), sportCs("kayak")], a: hm(95), b: hm(42), c: hm(120), p: paceStr(307), none: paceStr(null) }))
"""


def _node(tmp_path):
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node is not installed")
    f = tmp_path / "probe.mjs"
    f.write_text(PROBE % SRC)
    r = subprocess.run([exe, "--experimental-strip-types", str(f)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        pytest.skip("this node cannot run TypeScript: " + r.stderr[-200:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_week_totals_count_this_week_and_skip_excluded(tmp_path):
    out = _node(tmp_path)
    # Monday 2 Nov to Wednesday 4 Nov: the run (50) and the ride (70); the excluded run and last week's run do not count
    assert out["week"] == {"allMin": 120, "runMin": 50, "ascent": 300, "descent": 290, "floors": 100}
    assert out["empty"] == {"allMin": 0, "runMin": 0, "ascent": 0, "descent": 0, "floors": 0}
    assert out["last"] == "2026-11-03T18:00:00"                       # the excluded later run is not "last"
    assert (out["a"], out["b"], out["c"]) == ("1 h 35 min", "42 min", "2 h 00 min")
    assert out["p"] == "5:07" and out["none"] is None


def test_the_four_new_cards_are_accepted_and_the_cap_is_sixteen(client):
    register(client, "rail6@test.cz", "Rail Six", "runner")
    ids = ["ttime", "rtime", "elev", "last"]
    assert client.patch("/api/auth/settings", json={"today_cards": ids}).json()["today_cards"] == ids
    every = ["week", "load", "mech", "hrv", "rhr", "sleep", "readiness", "race", "recovery", "form", "fit", "fat"] + ids
    assert len(every) == 16
    assert client.patch("/api/auth/settings", json={"rail_cards": every + ["bogus"]}).json()["rail_cards"] == every


def test_recent_activities_are_newest_first_skip_excluded_and_cap(tmp_path):
    """feedback #231 — the list behind the cards: newest first, an excluded activity never shows, at most n"""
    out = _node(tmp_path)
    assert out["recent"] == ["2026-11-03T18:00:00", "2026-11-02T07:00:00"]   # the excluded run of 3 Nov 19:00 is skipped
    assert out["all"] == 3 and out["none_recent"] == 0
    assert out["sports"] == ["běh", "běh", "kolo", "jiný sport"]


def test_weekly_totals_follow_the_week_rules_and_end_with_the_running_week(tmp_path):
    """feedback #228-#230 — the trend sheets: Monday-Sunday weeks, oldest first, the running week last;
    all sports for the training time, runs only for run time and climb, excluded activities never count"""
    out = _node(tmp_path)
    # weeks: 19 Oct, 26 Oct (the run of 30 Oct: 60 min), 2 Nov (run 50 + ride 70; the excluded run is left out)
    assert out["wAll"] == [{"t": "2026-10-19", "v": 0}, {"t": "2026-10-26", "v": 60}, {"t": "2026-11-02", "v": 120}]
    assert out["wRun"] == [{"t": "2026-10-19", "v": 0}, {"t": "2026-10-26", "v": 60}, {"t": "2026-11-02", "v": 50}]
    assert out["wUp"] == [{"t": "2026-10-26", "v": 500}, {"t": "2026-11-02", "v": 300}]
