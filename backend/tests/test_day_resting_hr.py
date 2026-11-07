"""feedback #227 (engine v0.12.21, display only): the readiness detail carries the resting heart
rate of the awake day outside training and sleep (dayload's daily `rest_hr_med`) next to the
night's. It is not scored: the readiness score is the same whatever the daytime values are."""
from datetime import timedelta

from app import models
from app.metrics import capacity as C
from app.metrics import engine as E


def _runner(db, rid, day_hr):
    """57 days of nights; `day_hr(k)` is the daytime resting HR k days back (None = not recorded)."""
    t = E.today_date()
    db.add(models.Runner(id=rid, name="Den", sex="m", birth_year=1990))
    for k in range(0, 57):
        d = t - timedelta(days=k)
        db.add(models.DailyMetric(runner_id=rid, date=d.isoformat(), resting_hr=50 + (k % 3), hrv_ms=70 + (k % 4),
                                  sleep_h=7.5, rest_hr_med=day_hr(k)))
    db.commit()
    return t


def test_the_inputs_carry_the_daytime_resting_hr(client, db_session):
    t = _runner(db_session, "dayrhr-1", lambda k: 62 + (k % 5))
    inp = C.readiness_inputs(db_session, "dayrhr-1", t.isoformat())
    week = [62 + (k % 5) for k in range(0, 7)]
    base = [62 + (k % 5) for k in range(8, 57)]
    assert inp["week"]["dayRhr"] == round(sum(week) / 7)
    assert inp["base"]["dayRhr"] == round(sum(base) / len(base))
    lo, hi = inp["range"]["dayRhr"]
    assert lo < inp["base"]["dayRhr"] < hi
    assert len(inp["nights"]) == 7 and all(n["dayRhr"] is not None for n in inp["nights"])


def test_no_daytime_data_means_no_value_and_no_range(client, db_session):
    t = _runner(db_session, "dayrhr-2", lambda k: None)
    inp = C.readiness_inputs(db_session, "dayrhr-2", t.isoformat())
    assert inp["week"]["dayRhr"] is None and inp["base"]["dayRhr"] is None and inp["range"]["dayRhr"] is None


def test_the_readiness_score_does_not_depend_on_it(client, db_session):
    t = _runner(db_session, "dayrhr-3", lambda k: 60 + (k % 4))
    day = t.isoformat()
    before = C.readiness_by_day(db_session, "dayrhr-3", [day])[day]
    for m in db_session.query(models.DailyMetric).filter_by(runner_id="dayrhr-3").all():
        m.rest_hr_med = (m.rest_hr_med or 60) + 25            # a much higher daytime heart rate
    db_session.commit()
    after = C.readiness_by_day(db_session, "dayrhr-3", [day])[day]
    assert before[2] == after[2] and before == after


def test_the_engine_version_names_the_change():
    # the version moves on with later engine changes (v0.12.22 added the VO2max estimate); this one must stay in the history
    assert "v0.12.21 (" in open(E.__file__).read()
