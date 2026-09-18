"""Region-scoped triage queue: a physio sees their own region by default,
can opt into the whole platform, and a physio with no clinic on file falls
back to seeing everything.
"""
from .conftest import login, register

PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"   # phy-0001 · Fyzio Holešovice, Praha 7 → region "praha"


def test_clinic_scope_is_region_only(client):
    login(client, PHYSIO_EMAIL, expected_role="physio")
    clinic = client.get("/api/triage?status=open&scope=clinic").json()
    assert clinic, "expected open cases in the physio's own region"
    assert all(t["region"] == "praha" for t in clinic)
    assert all(t["in_region"] for t in clinic)


def test_all_scope_includes_other_regions(client):
    login(client, PHYSIO_EMAIL, expected_role="physio")
    clinic = client.get("/api/triage?status=open&scope=clinic").json()
    everything = client.get("/api/triage?status=open&scope=all").json()
    assert len(everything) >= len(clinic)
    # the platform-wide view reaches at least one non-Praha region
    assert any(t["region"] != "praha" for t in everything)


def test_physio_without_clinic_sees_all(client):
    register(client, "noclinicphysio@test.cz", "Bez Kliniky", "physio", "testpass123")
    clinic = client.get("/api/triage?status=open&scope=clinic").json()
    everything = client.get("/api/triage?status=open&scope=all").json()
    assert len(clinic) == len(everything)   # no clinic → no regional filter
