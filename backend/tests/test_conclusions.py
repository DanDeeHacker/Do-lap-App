"""Post-visit conclusion — draft → approve, physio-only writes, runner reads
only after approval, and that approval with a structured OSTRC outcome writes
the authoritative grade-A InjuryReport (source='physio_conclusion').
"""
from .conftest import login, register

RUNNER_EMAIL = "adela@demo.cz"          # run-0001, already claimed by phy-0001 in the seed
PHYSIO_EMAIL = "havlickova@fyzioholesovice.cz"   # phy-0001
RUNNER_ID = "run-0001"
PHYSIO_ID = "phy-0001"


def _book(client):
    login(client, RUNNER_EMAIL)
    r = client.post(f"/api/runners/{RUNNER_ID}/bookings",
                    json={"physio_id": PHYSIO_ID, "kind": "assessment", "days_ahead": 0})
    assert r.status_code == 200
    return r.json()["id"]


def _signal_ids(a):
    return {s["id"] for s in a.get("signals", [])}


def test_full_conclusion_flow_writes_grade_a_outcome(client):
    bid = _book(client)

    login(client, PHYSIO_EMAIL, expected_role="physio")
    c = client.post(f"/api/bookings/{bid}/conclusion").json()
    cid = c["id"]
    assert c["status"] == "draft"

    client.patch(f"/api/conclusions/{cid}", json={
        "summary": "Přetížení lýtkového komplexu, bez známek strukturální léze.",
        "finding": "Tendinopatie Achillovy šlachy, časná fáze",
        "has_outcome": True, "out_participation": 17, "out_volume": 8,
        "out_performance": 8, "out_pain": 17, "out_region": "achilles", "out_side": "P",
    })

    # runner may not read it before approval
    login(client, RUNNER_EMAIL)
    assert client.get(f"/api/conclusions/{cid}").status_code == 403

    # approve
    login(client, PHYSIO_EMAIL, expected_role="physio")
    appr = client.post(f"/api/conclusions/{cid}/approve")
    assert appr.status_code == 200
    body = appr.json()
    assert body["status"] == "approved"
    assert body["injury_report_id"] is not None

    # runner can now read it, and it shows up in their bootstrap
    login(client, RUNNER_EMAIL)
    assert client.get(f"/api/conclusions/{cid}").status_code == 200
    boot = client.get(f"/api/runners/{RUNNER_ID}/bootstrap").json()
    assert any(x["id"] == cid for x in boot["conclusions"])

    # and the engine now carries a grade-A confirmed-injury signal
    a = client.get(f"/api/runners/{RUNNER_ID}/assessment").json()
    assert "injury" in _signal_ids(a)
    sig = next(s for s in a["signals"] if s["id"] == "injury")
    assert sig["grade"] == "A"
    assert "Potvrzené zranění" in sig["name"]
    assert a["injury"]["active"]["confirmed"] is True
    assert a["injury"]["active"]["severity"] == 50


def test_runner_cannot_open_conclusion(client):
    bid = _book(client)
    login(client, RUNNER_EMAIL)
    assert client.post(f"/api/bookings/{bid}/conclusion").status_code == 403


def test_other_physio_cannot_conclude_unowned_booking(client):
    bid = _book(client)
    register(client, "otherphysio@test.cz", "Jiný Fyzio", "physio", "testpass123")
    assert client.post(f"/api/bookings/{bid}/conclusion").status_code == 403


def test_approve_empty_conclusion_rejected(client):
    bid = _book(client)
    login(client, PHYSIO_EMAIL, expected_role="physio")
    cid = client.post(f"/api/bookings/{bid}/conclusion").json()["id"]
    r = client.post(f"/api/conclusions/{cid}/approve")
    assert r.status_code == 422   # no summary yet
