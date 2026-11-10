"""The access history shows "<who> <did> <what>" in words. Every resource the audit registry logs needs a label,
or the physio and the runner see raw keys such as clinic_test or prom (found while preparing the report's
physiotherapist views, 2026-11-10)."""
from app import audit as AU
from app import moat as M
from app.routers.records import RESOURCE_CS


def test_every_audited_resource_has_a_label():
    logged = {d[1] for d in AU.ROUTES.values() if isinstance(d, tuple) and d[0] not in ("self", "exempt")}
    assert not logged - set(RESOURCE_CS), sorted(logged - set(RESOURCE_CS))


def test_clinic_test_names_carry_no_unit():
    # the option shows "<name> (<unit>)"; a unit inside the name printed it twice
    for t in M.TESTS.values():
        assert f"({t['unit']})" not in t["name_cs"], t["name_cs"]
