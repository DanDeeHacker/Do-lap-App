"""v0.6 outcome capture — OSTRC-H injury reports. Covers the runner-self
write scope, OSTRC value validation, the weekly-prompt-due flag, that an
active report becomes a symptom-axis signal, and that resolving it clears
that signal again.

Each test registers a fresh runner so injury state can't bleed between
tests through the session-shared seed DB.
"""
from .conftest import login, register

RUNNER_EMAIL = "adela@demo.cz"          # a seeded runner, used only for cross-runner scoping


_counter = [0]


def _fresh_runner(client):
    _counter[0] += 1
    n = _counter[0]
    resp = register(client, f"injrunner{n}@test.cz", f"Injury Runner {n}", "runner")
    return resp.json()["runner_id"]


def _signal_ids(assessment):
    return {s["id"] for s in assessment.get("signals", [])}


def test_report_injury_creates_symptom_signal(client):
    rid = _fresh_runner(client)
    body = {"kind": "adhoc", "q_participation": 17, "q_volume": 17,
            "q_performance": 8, "q_pain": 17, "body_region": "achilles", "body_side": "P"}
    r = client.post(f"/api/runners/{rid}/injury-report", json=body)
    assert r.status_code == 200
    a = r.json()
    assert "injury" in _signal_ids(a)
    assert a["injury"]["active"]["severity"] == 59
    assert a["injury"]["active"]["confirmed"] is False   # self-report → grade B
    injury_sig = next(s for s in a["signals"] if s["id"] == "injury")
    assert injury_sig["grade"] == "B"
    assert injury_sig["pts"] > 0


def test_invalid_ostrc_value_rejected(client):
    rid = _fresh_runner(client)
    r = client.post(f"/api/runners/{rid}/injury-report",
                    json={"q_participation": 10})   # 10 is not an OSTRC level
    assert r.status_code == 422


def test_runner_cannot_report_for_another_runner(client):
    login(client, RUNNER_EMAIL)  # run-0001
    r = client.post("/api/runners/run-0002/injury-report", json={"q_pain": 8})
    assert r.status_code == 403


def test_weekly_prompt_due_flips_after_report(client):
    rid = _fresh_runner(client)
    before = client.get(f"/api/runners/{rid}/bootstrap").json()
    assert before["injury_prompt_due"] is True   # no self report yet

    client.post(f"/api/runners/{rid}/injury-report", json={"kind": "weekly"})
    after = client.get(f"/api/runners/{rid}/bootstrap").json()
    assert after["injury_prompt_due"] is False


def test_resolve_clears_injury_signal(client):
    rid = _fresh_runner(client)
    client.post(f"/api/runners/{rid}/injury-report",
                json={"kind": "adhoc", "q_participation": 25, "q_pain": 25,
                      "body_region": "shin", "body_side": "L"})
    active = client.get(f"/api/runners/{rid}/assessment").json()
    assert "injury" in _signal_ids(active)

    r = client.post(f"/api/runners/{rid}/injury-report", json={"resolve": True})
    assert r.status_code == 200
    assert "injury" not in _signal_ids(r.json())
