"""
Bulk-provision resident logins from imported residents, and phone login.

The promises: an admin can hand a building's residents portal access in one call;
each provisioned resident signs in by phone with a shared password and lands on
their own flat; re-running skips those already done; and the phone login never
weakens the existing email login.

    python -m pytest backend/tests/test_provisioning.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token, hash_password

client = TestClient(app)

ADMIN_ID = "00000000-0000-0000-0000-0000000000b1"
DEFAULT_PW = "society123"


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'PV-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="PV-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.User(id=ADMIN_ID, society_id=soc.id, email="pv-admin@pv-test.in",
                      password_hash=hash_password("adminpw"), role="society_admin"))
        db.add(m.Wing(society_id=soc.id, name="A", floors=10, flats_per_floor=4))
        db.flush()
        return soc.id


def _hdr(society_id):
    return {"Authorization": "Bearer " + create_access_token(
        user_id=ADMIN_ID, society_id=str(society_id), role="society_admin")}


def _wing_id(society_id):
    with system_session() as db:
        return str(db.execute(text(
            "SELECT id FROM wings WHERE society_id=:s AND name='A'"),
            {"s": society_id}).scalar_one())


def _flat(society_id, number="101"):
    r = client.post("/flats", headers=_hdr(society_id),
                    json={"wing_id": _wing_id(society_id), "flat_number": number, "floor": 1})
    assert r.status_code == 201, r.text
    return r.json()


def _resident(society_id, flat_code, name, phone):
    r = client.post("/residents", headers=_hdr(society_id),
                    json={"flat_number": flat_code, "name": name, "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


def _provision(society_id, **body):
    body.setdefault("default_password", DEFAULT_PW)
    return client.post("/users/provision-residents", headers=_hdr(society_id), json=body)


# --- Provisioning -----------------------------------------------------------

def test_provision_creates_a_phone_login_that_reaches_the_flat(society):
    _flat(society)
    _resident(society, "A-101", "Priya Sharma", "+91 95550 00001")

    r = _provision(society)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created_count"] == 1
    assert body["created"][0]["phone"] == "9555000001"  # bare 10 digits, no +91

    # The resident can log in with just the 10-digit number (or with +91 — both
    # normalise to the same thing).
    login = client.post("/auth/login", json={"email": "9555000001", "password": DEFAULT_PW})
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "resident"

    token = login.json()["access_token"]
    me = client.get("/portal/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200, me.text
    assert me.json()["flat_number"] == "A-101"


def test_provision_is_idempotent(society):
    _flat(society)
    _resident(society, "A-101", "Priya Sharma", "+919555000001")
    assert _provision(society).json()["created_count"] == 1
    second = _provision(society).json()
    assert second["created_count"] == 0
    assert second["skipped_count"] == 1
    assert second["skipped"][0]["reason"] == "already has a login"


def test_residents_without_a_phone_are_skipped(society):
    _flat(society)
    _resident(society, "A-101", "No Phone", None)
    body = _provision(society).json()
    assert body["created_count"] == 0
    assert body["skipped"][0]["reason"] == "no phone on record"


def test_duplicate_phone_is_skipped(society):
    _flat(society, "101")
    _flat(society, "102")
    _resident(society, "A-101", "Priya Sharma", "+919555000001")
    _resident(society, "A-102", "Rahul Verma", "+919555000001")  # same phone
    body = _provision(society).json()
    assert body["created_count"] == 1
    assert any(s["reason"] == "phone already used by another login" for s in body["skipped"])


def test_wing_filter_narrows_provisioning(society):
    # Second wing with its own resident.
    with system_session() as db:
        db.add(m.Wing(society_id=society, name="B", floors=5, flats_per_floor=4))
        db.flush()
    _flat(society, "101")
    r = client.post("/flats", headers=_hdr(society), json={
        "wing_id": str(next(w for w in client.get('/wings', headers=_hdr(society)).json()
                            if w["name"] == "B")["id"]),
        "flat_number": "201", "floor": 2})
    assert r.status_code == 201
    _resident(society, "A-101", "Aoife A", "+919555000001")
    _resident(society, "B-201", "Bala B", "+919555000002")

    body = _provision(society, wing_id=_wing_id(society)).json()  # wing A only
    assert body["created_count"] == 1
    assert body["created"][0]["flat_number"] == "A-101"


# --- Login safety -----------------------------------------------------------

def test_email_login_still_works_for_admins(society):
    r = client.post("/auth/login", json={"email": "pv-admin@pv-test.in", "password": "adminpw"})
    assert r.status_code == 200
    assert r.json()["role"] == "society_admin"


def test_wrong_password_is_rejected_for_phone_login(society):
    _flat(society)
    _resident(society, "A-101", "Priya Sharma", "+919555000001")
    _provision(society)
    r = client.post("/auth/login", json={"email": "+919555000001", "password": "wrong"})
    assert r.status_code == 401


def test_an_email_that_is_not_a_phone_does_not_match_a_phoneless_admin(society):
    # A garbage identifier must not fall through to some phone-null row.
    r = client.post("/auth/login", json={"email": "nobody@nowhere.in", "password": "x"})
    assert r.status_code == 401
