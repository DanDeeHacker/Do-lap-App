"""Owner request 2026-10-26: the week's plan in Apple / Google Calendar through a secret .ics link
(routers/calendar.py) — created, rotated and switched off in the profile; the feed itself needs only
the token."""
from datetime import date, datetime, timezone

from app.routers.calendar import _fold, ics


def test_the_feed_is_valid_icalendar_with_one_all_day_event_per_session():
    plan = {"days": [
        {"date": "2026-10-26", "items": [{"kind": "done", "label": "Odběhnuto", "km": 8.4}]},
        {"date": "2026-10-27", "items": [{"kind": "run", "type": "lehký", "label": "Lehký běh", "km": {"lo": 6.2, "hi": 7.8},
                                          "hr": [131, 147], "zones": "Z2", "pace": [313, 339], "durationMin": [33, 44],
                                          "note": "4–6 stupňovaných rovinek", "pinned": True},
                                         {"kind": "strength", "label": "Posilování", "session": "B · Odolnost",
                                          "program": "Runner's must-have", "min": [30, 45], "rpe": "6–7 z 10"}]},
        {"date": "2026-10-28", "items": [{"kind": "rest", "label": "Volno"}]},
    ]}
    out = ics(plan, "run-0001", "cs", "https://app/app/training", datetime(2026, 10, 26, 8, tzinfo=timezone.utc))
    assert out.startswith("BEGIN:VCALENDAR\r\n") and out.endswith("END:VCALENDAR\r\n")
    assert out.count("BEGIN:VEVENT") == 3                      # the rest day isn't an event
    assert "DTSTART;VALUE=DATE:20261027" in out and "DTEND;VALUE=DATE:20261028" in out
    assert "SUMMARY:🏃 Lehký běh 6\\,2–7\\,8 km" in out and "Vaše volba v Plánu týdne." in out
    assert all(len(line.encode()) <= 75 for line in out.split("\r\n"))
    # the same day keeps the same UID, so the calendar updates the event instead of duplicating it
    again = ics(plan, "run-0001", "cs", "https://app/app/training", datetime(2026, 10, 27, 8, tzinfo=timezone.utc))
    uids = lambda s: [l for l in s.split("\r\n") if l.startswith("UID:")]
    assert uids(out) == uids(again)


def test_english_runners_get_the_feed_in_english():
    plan = {"days": [{"date": "2026-10-27", "items": [{"kind": "run", "type": "lehký", "label": "Lehký běh",
                                                       "km": {"lo": 6.2, "hi": 7.8}, "hr": [131, 147], "zones": "Z2"}]}]}
    out = ics(plan, "r", "en", "https://app/app/training", datetime(2026, 10, 26, tzinfo=timezone.utc)).replace("\r\n ", "")
    assert "Easy run 6.2–7.8 km" in out and "131–147 bpm" in out and "Lehký" not in out


def test_long_lines_fold_on_character_boundaries():
    line = "DESCRIPTION:" + "Příliš žluťoučký kůň úpěl ďábelské ódy. " * 6
    folded = _fold(line)
    assert all(len(p.encode()) <= 75 for p in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line


def test_the_link_is_created_rotated_used_and_switched_off(client, db_session):
    from .conftest import register
    rid = register(client, "cal1026@test.cz", "Kalendář", "runner").json()["runner_id"]
    assert client.get(f"/api/runners/{rid}/calendar-feed").json() == {"on": False}
    f = client.post(f"/api/runners/{rid}/calendar-feed").json()
    assert f["on"] and f["url"].endswith(".ics") and f["webcal"].startswith("webcal://") and "calendar.google.com" in f["google"]
    r = client.get("/api/calendar/" + f["url"].rsplit("/", 1)[1])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar") and "BEGIN:VCALENDAR" in r.text
    f2 = client.post(f"/api/runners/{rid}/calendar-feed").json()
    assert f2["url"] != f["url"]
    assert client.get("/api/calendar/" + f["url"].rsplit("/", 1)[1]).status_code == 404     # the old link stops
    assert client.delete(f"/api/runners/{rid}/calendar-feed").json() == {"on": False}
    assert client.get("/api/calendar/" + f2["url"].rsplit("/", 1)[1]).status_code == 404


def test_someone_else_cant_read_or_create_the_link(client, db_session):
    from .conftest import register
    rid = register(client, "cal1026a@test.cz", "Kalendář A", "runner").json()["runner_id"]
    client.cookies.clear()
    register(client, "cal1026b@test.cz", "Kalendář B", "runner")
    assert client.get(f"/api/runners/{rid}/calendar-feed").status_code in (403, 404)
    assert client.post(f"/api/runners/{rid}/calendar-feed").status_code in (403, 404)
