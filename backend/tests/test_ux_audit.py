"""UX audit 2026-10 (first-time runner): the server side of the fixes.

F02 — a day without a night from the watch has no readiness in the history (the trend
drew it as 100 %); F14 — the assistant never prints an internal readiness key; F10 —
the contact-balance signal shows its measurement in its own unit, not in "p. b."
(which also meant the Skóre effect); F07 — no "baseline" in the runner-facing notes."""
from app import history as H
from app.assistant import facts as AF
from app.metrics import engine as E


def _day(readiness):
    return {"_cut": "2026-10-01", "quadrant": "stable", "overall": 10, "tier": "ok", "mech": 0, "load": 0,
            "symp": 0, "readiness": readiness, "signals": []}


def test_history_leaves_a_day_without_a_night_empty():
    row = H._quad_row(_day({"score": 100, "morningScore": 100, "known": False}))
    assert row["readiness"] is None and row["readinessMorning"] is None


def test_history_keeps_a_known_day():
    row = H._quad_row(_day({"score": 72, "morningScore": 80, "known": True}))
    assert row["readiness"] == 72 and row["readinessMorning"] == 80


def test_history_without_the_flag_behaves_as_before():
    # older payloads (before the "known" flag) still show their score
    row = H._quad_row(_day({"score": 64}))
    assert row["readiness"] == 64 and row["readinessMorning"] == 64


def test_assistant_names_every_readiness_part_and_hides_unknown_keys():
    a = {"readiness": {"score": 61, "parts": {"hrv": 0.4, "dayLoad": 0.2, "session": 0.3, "dayStressNow": 0.1, "mystery": 0.5}}}
    parts = AF._readiness(a).get("whatLowersReadiness") or {}
    labels = " ".join(parts)
    assert "pohyb mimo trénink" in labels and "dnešní trénink" in labels and "tep v klidu dnes" in labels
    assert "dayLoad" not in labels and "mystery" not in labels and "session" not in labels


def test_mechanics_notes_use_plain_words():
    for note in ("Vaši normu techniky zatím poznáváme", "Norma techniky je spolehlivá"):
        assert note in open(E.__file__, encoding="utf-8").read()
    src = open(E.__file__, encoding="utf-8").read()
    assert "Baseline se zatím buduje" not in src and 'f"Baseline {rcv' not in src


def test_contact_balance_value_is_not_in_percentage_points():
    src = open(E.__file__, encoding="utf-8").read()
    i = src.index('mech_terms.append(("bal", "Posun v symetrii kontaktu"')
    line = src[i:src.index("\n", i)]
    assert "p.b." not in line and "obvykle" in line
