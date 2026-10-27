"""The simulated runners (owner request 2026-10-27, "an agent that uses the app like a runner").
Five people the pilot will have, each with a body (baselines the generator draws from), a usual
week before the simulation starts, habits (how they follow the plan and use the app) and life
events on given simulation days. Behaviour can be calibrated from the pilot's aggregated usage
(calibration.py); bodies are always made up — real health data never enters a persona."""

# kinds the generator knows: easy, recovery, long, tempo, intervals, trail, cycling, strength, swim
PERSONAS = {
    "tereza": {
        "name": "Tereza", "label": "začátečnice, první rok běhání",
        "sex": "f", "birth_year": 1998, "weight_kg": 62, "running_months": 7, "hr_max": 194,
        "body": {"hrv": 62, "rhr": 56, "sleep": 7.6, "easy_pace": 395, "cad": 166, "vr": 8.6, "gct": 268, "bal": 50.1},
        "week": {1: ("easy", 4.5), 3: ("easy", 5.0), 6: ("long", 7.0)},
        "habits": {"compliance": 0.9, "overshoot": 0.0, "checkin": 0.85, "feedback": 0.8, "open": 0.9,
                   "hours": [7, 21], "stubborn": False},
        "events": [
            {"kind": "bad_sleep", "from": 15, "to": 19, "note": "zkouškové, spí po 5 hodinách"},
            {"kind": "illness", "from": 34, "to": 37, "note": "nachlazení"},
        ],
    },
    "martin": {
        "name": "Martin", "label": "maratonec, cíl maraton za 10 týdnů",
        "sex": "m", "birth_year": 1987, "weight_kg": 74, "running_months": 72, "hr_max": 186,
        "body": {"hrv": 58, "rhr": 47, "sleep": 7.1, "easy_pace": 318, "cad": 176, "vr": 7.2, "gct": 238, "bal": 49.9},
        "week": {0: ("easy", 9.0), 1: ("intervals", 12.0), 2: ("easy", 10.0), 3: ("tempo", 12.0),
                 5: ("long", 22.0), 6: ("recovery", 7.0)},
        "habits": {"compliance": 0.8, "overshoot": 0.3, "checkin": 0.6, "feedback": 0.5, "open": 0.95,
                   "hours": [6, 12, 22], "stubborn": False},
        "goal": {"name": "Pražský podzimní maraton", "day": 70, "km": 42.2},
        "events": [
            {"kind": "no_watch", "from": 30, "to": 32, "note": "služební cesta, hodinky doma"},
        ],
    },
    "jana": {
        "name": "Jana", "label": "návrat po Achillově šlaše",
        "sex": "f", "birth_year": 1990, "weight_kg": 58, "running_months": 48, "hr_max": 189,
        "body": {"hrv": 66, "rhr": 51, "sleep": 7.4, "easy_pace": 352, "cad": 172, "vr": 7.8, "gct": 252, "bal": 50.6},
        "week": {1: ("easy", 5.0), 3: ("easy", 5.0), 5: ("long", 7.5)},
        "habits": {"compliance": 0.95, "overshoot": 0.0, "checkin": 0.95, "feedback": 0.95, "open": 0.9,
                   "hours": [7, 20], "stubborn": False},
        "prior_injury": ("Achillova šlacha", 10, "right"),
        "events": [
            {"kind": "pain", "from": 12, "to": 16, "site": "Achillova šlacha", "side": "P", "score": 3, "note": "ráno ztuhlá šlacha"},
            {"kind": "pain", "from": 40, "to": 44, "site": "Achillova šlacha", "side": "P", "score": 5, "note": "zhoršení po kopcích"},
        ],
    },
    "eva": {
        "name": "Eva", "label": "sleduje cyklus, běhá i nemocná",
        "sex": "f", "birth_year": 1993, "weight_kg": 66, "running_months": 36, "hr_max": 191,
        "body": {"hrv": 55, "rhr": 54, "sleep": 7.0, "easy_pace": 340, "cad": 170, "vr": 8.0, "gct": 255, "bal": 49.6},
        "week": {0: ("easy", 7.0), 2: ("tempo", 8.0), 4: ("easy", 7.0), 6: ("long", 12.0)},
        "habits": {"compliance": 0.75, "overshoot": 0.15, "checkin": 0.7, "feedback": 0.6, "open": 0.8,
                   "hours": [8, 19], "stubborn": True},
        "cycle": {"length": 28, "start_offset": 5},
        "events": [
            {"kind": "illness", "from": 18, "to": 22, "note": "horečka, přesto chce běžet"},
        ],
    },
    "pavel": {
        "name": "Pavel", "label": "padesátník, kopce a kolo, aplikaci otvírá nepravidelně",
        "sex": "m", "birth_year": 1974, "weight_kg": 80, "running_months": 180, "hr_max": 172,
        "body": {"hrv": 41, "rhr": 52, "sleep": 6.8, "easy_pace": 360, "cad": 168, "vr": 8.2, "gct": 262, "bal": 50.3},
        "week": {1: ("trail", 10.0), 2: ("cycling", 70), 3: ("easy", 8.0), 5: ("long_trail", 16.0), 6: ("cycling", 90)},
        "habits": {"compliance": 0.7, "overshoot": 0.2, "checkin": 0.4, "feedback": 0.3, "open": 0.45,
                   "hours": [22], "stubborn": False},
        "events": [
            {"kind": "bad_sleep", "from": 25, "to": 27, "note": "noční směny"},
        ],
    },
}

KEYS = tuple(PERSONAS)
EMAIL = "{key}@persona.doslap.invalid"
PROVIDER = "persona"
RID = "persona_{key}"


def events_on(p: dict, day_no: int) -> list[dict]:
    return [e for e in p.get("events", []) if e["from"] <= day_no <= e["to"]]
