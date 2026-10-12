"""Owner request 2026-10-12: the assistant explains what the data and the engine imply for
the next activities — every option today with what it takes and what it leaves for
tomorrow (outlook.py), the week's plan (week_plan.py), a prompt section for it, a
validator that lets an allowed option be described and the rule-based fallback."""
from app.assistant import facts as FA
from app.assistant import selector as SEL
from app.assistant import service as S
from app.assistant import validate as VAL
from app.metrics import engine as E
from .test_assistant import FACTS, SOURCES
from .test_guidance import _runner


def test_what_if_questions_get_the_options_and_the_week():
    for q, typ in [("Co když dnes místo běhu dám kolo?", "kolo"), ("Co dnešní trénink udělá se zítřkem?", None),
                   ("Jak vypadá zbytek mého týdne?", None), ("Můžu si dát intervaly?", "kvalitní"),
                   ("Kolik ještě můžu dnes uběhnout?", None)]:
        sel = SEL.classify(q)
        assert {"options", "weekplan", "types"} <= set(sel["slices"]), q
        assert sel["askedType"] == typ, q
    assert "options" not in SEL.classify("Proč mám nízké HRV?")["slices"]
    assert "options" in SEL.classify("Co s tím?", {"kind": "tab", "id": "training"})["slices"]


def test_every_option_says_what_it_leaves_for_tomorrow(client, db_session):
    rid, r = _runner(client, db_session, "opt1@test.cz")
    a = E.get_or_refresh_assessment(db_session, rid)
    g = a["guidance"]
    f = FA.build(db_session, rid, a, SEL.classify("Co když dnes místo běhu dám kolo?"))
    opts = f["options"]["list"]
    assert "noc jako dnešní" in f["options"]["howToRead"]
    labels = {t["label"]: k for k, t in g["types"].items()}
    assert len(opts) == len(g["types"])
    rec = next(o for o in opts if "(doporučení na dnešek)" in o)
    assert rec.startswith(g["types"][g["type"]]["label"])
    for o in opts:
        k = labels[o.split(":")[0].split(" (")[0]]
        if g["types"][k]["allowed"] and k in ("lehký", "kvalitní", "kolo", "voda") and not g.get("afterDone"):
            assert "zítra" in o, o                      # what it leaves for tomorrow, from the outlook
        if not g["types"][k]["allowed"]:
            assert "dnes ne" in o, o
    kolo = next(o for o in opts if o.startswith("Kolo"))
    if g["types"]["kolo"]["allowed"]:
        assert "šlachy šetří" in kolo and "zítra" in kolo
        if (g["week"]["channels"].get("systemic") or {}).get("todayMax") is not None:
            assert "celková zátěž ≈" in kolo
    wp = f["weekPlan"]
    assert wp.get("restOfWeek") or wp.get("override") or E.today_date().weekday() == 6


def test_after_a_session_today_the_other_runs_are_not_offered():
    a = {"guidance": {"type": "volno", "rank": ["volno", "lehký", "kolo"], "afterDone": {"type": "volno", "text": "Dnes už máte hotovo."},
                      "types": {"volno": {"label": "Volno", "allowed": True},
                                "lehký": {"label": "Lehký běh", "allowed": True, "km": {"lo": 6, "hi": 8}},
                                "kolo": {"label": "Kolo", "allowed": True, "cross": True, "durationMin": [40, 60]}}}}
    o = FA._options(a)
    assert o["doneToday"] == "Dnes už máte hotovo."
    assert o["list"][1].startswith("Lehký běh: dnes už ne")
    assert o["list"][2].startswith("Kolo (navíc k dnešnímu tréninku): 40–60 min")


def test_an_allowed_harder_option_may_be_described_a_blocked_one_not():
    alt = ("Dnes je doporučený lehký běh. Co to znamená dál: kvalitní trénink dnes aplikace také dovoluje, "
           "ale vezme víc z dnešních limitů. Co s tím: držte se raději lehkého běhu.")
    allowed = {**FACTS, "sessionTypes": {"kvalitní": {"label": "Kvalitní trénink", "allowed": True}}}
    blocked = {**FACTS, "sessionTypes": {"kvalitní": {"label": "Kvalitní trénink", "allowed": False, "whyNot": "nízká připravenost"}}}
    assert "contradicts_recommendation" not in [i["code"] for i in VAL.validate(alt, allowed, SOURCES)["issues"]]
    push = "Dnes si klidně dejte intervaly, tělo je v pohodě a zvládne to."
    assert "contradicts_recommendation" in [i["code"] for i in VAL.validate(push, blocked, SOURCES)["issues"]]
    assert "contradicts_recommendation" in [i["code"] for i in VAL.validate(push, FACTS, SOURCES)["issues"]]


def test_the_new_section_is_a_heading_not_a_claim():
    t = VAL.tidy("Dnes lehce.\n3. Co to znamená dál: zítra běh nejvýš 8,0 km.")
    assert "3." not in t and "Co to znamená dál:" in t


def test_fallback_explains_the_option_and_the_week():
    facts = {"today": {"type": "lehký", "label": "Lehký běh", "km": "6,0–8,0 km", "reasons": ["Obvyklý lehký den."]},
             "sessionTypes": {"kolo": {"label": "Kolo", "allowed": True}},
             "options": {"list": ["Lehký běh (doporučení na dnešek): 6,0–8,0 km; zítra běh nejvýš 9,0 km.",
                                  "Kolo: 40–60 min; zítra běh nejvýš 10,0 km."]},
             "weekPlan": {"tomorrow": "st Volno", "restOfWeek": ["st Volno", "čt Lehký běh 6–8 km"]}}
    txt = S.fallback_answer(SEL.classify("Co když dnes místo běhu dám kolo?"), facts, [], [])
    assert "Co to znamená dál: Kolo: 40–60 min; zítra běh nejvýš 10,0 km." in txt
    week = S.fallback_answer(SEL.classify("Jak vypadá zbytek mého týdne?"), facts, [], [])
    assert "Plán zbytku týdne: st Volno, čt Lehký běh 6–8 km." in week
    assert VAL.validate(txt, facts, [])["ok"]
