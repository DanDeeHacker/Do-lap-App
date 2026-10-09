"""Accounts from before the Kapacitní engine are moved onto v3 once (the Trénink tab
exists only with v3 and the engine choice is owner-only), keeping the old mode."""
from sqlalchemy import create_engine, inspect, text

from app.main import _migrate


def test_old_accounts_move_to_v3_once_and_keep_the_previous_mode(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE runners (id VARCHAR PRIMARY KEY, name VARCHAR, engine_mode VARCHAR)"))
        c.execute(text("INSERT INTO runners VALUES ('run-1', 'A', 'v1'), ('run-2', 'B', 'v2'), "
                       "('run-3', 'C', 'v3'), ('run-4', 'D', NULL)"))
    _migrate(eng)
    assert "engine_mode_before_v3" in {c["name"] for c in inspect(eng).get_columns("runners")}
    with eng.begin() as c:
        rows = dict((r[0], (r[1], r[2])) for r in c.execute(text("SELECT id, engine_mode, engine_mode_before_v3 FROM runners")))
    assert rows["run-1"] == ("v3", "v1") and rows["run-2"] == ("v3", "v2")
    assert rows["run-3"] == ("v3", None)                     # already on v3: untouched
    assert rows["run-4"][0] == "v3"
    # an owner switching a runner back later is not undone by the next boot
    with eng.begin() as c:
        c.execute(text("UPDATE runners SET engine_mode = 'v1' WHERE id = 'run-1'"))
    _migrate(eng)
    with eng.begin() as c:
        assert c.execute(text("SELECT engine_mode FROM runners WHERE id = 'run-1'")).scalar() == "v1"
