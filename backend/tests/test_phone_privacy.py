"""
Per-society masking of resident mobile numbers.

When a society turns on `hide_resident_phones`, resident phone numbers come back
masked (last 4) in every admin-facing response — the residents list, the flat's
tenants, and a resident login's identifier on the users list. The resident still
sees their own number in full via the portal, and the gate resolves by phone
internally (unaffected).

    python -m pytest backend/tests/test_phone_privacy.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token, hash_password

client = TestClient(app)

ADMIN_ID = "00000000-0000-0000-0000-0000000000a9"
PHONE = "+91 95551 23456"          # normalises / stores as typed on the resident
FULL_TAIL = "3456"


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'PP-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="PP-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.User(id=ADMIN_ID, society_id=soc.id, email="pp-admin@pp-test.in",
                      password_hash=hash_password("x"), role="society_admin"))
        db.add(m.Wing(society_id=soc.id, name="A", floors=5, flats_per_floor=4))
        db.flush()
        return soc.id


def _hdr(society_id):
    return {"Authorization": "Bearer " + create_access_token(
        user_id=ADMIN_ID, society_id=str(society_id), role="society_admin")}


def _wing_id(society_id):
    with system_session() as db:
        return str(db.execute(text(
            "SELECT id FROM wings WHERE society_id=:s AND name='A'"), {"s": society_id}).scalar_one())


def _setup_flat_and_resident(society_id):
    r = client.post("/flats", headers=_hdr(society_id),
                    json={"wing_id": _wing_id(society_id), "flat_number": "101", "floor": 1})
    assert r.status_code == 201, r.text
    r = client.post("/residents", headers=_hdr(society_id),
                    json={"flat_number": "A-101", "name": "Priya Sharma", "phone": PHONE})
    assert r.status_code == 201, r.text
    return r.json()


def _set_hide(society_id, value: bool):
    with system_session() as db:
        db.execute(text("UPDATE societies SET hide_resident_phones=:v WHERE id=:s"),
                   {"v": value, "s": society_id})


def _resident_phone(society_id):
    rows = client.get("/residents", headers=_hdr(society_id)).json()
    return next(r["phone"] for r in rows if r["name"] == "Priya Sharma")


# --- Masking on the admin surfaces ------------------------------------------

def test_phone_is_full_when_the_toggle_is_off(society):
    _setup_flat_and_resident(society)
    phone = _resident_phone(society)
    assert phone == PHONE                 # unchanged
    assert "•" not in phone


def test_phone_is_masked_on_the_residents_list_when_on(society):
    _setup_flat_and_resident(society)
    _set_hide(society, True)
    phone = _resident_phone(society)
    assert phone.startswith("•")
    assert phone.endswith(FULL_TAIL)      # last 4 kept
    assert PHONE not in phone


def test_provisioned_login_identifier_is_masked_when_on(society):
    _setup_flat_and_resident(society)
    _set_hide(society, True)
    prov = client.post("/users/provision-residents", headers=_hdr(society),
                       json={"default_password": "shared123"})
    assert prov.status_code == 200, prov.text
    assert prov.json()["created_count"] == 1
    # The users list shows the login identifier masked.
    users = client.get("/users", headers=_hdr(society)).json()
    resident_login = next(u for u in users if u["role"] == "resident")
    assert resident_login["phone"].startswith("•")
    assert resident_login["phone"].endswith(FULL_TAIL)


# --- The resident still sees their own, and the gate still works -------------

def test_resident_sees_their_own_number_in_full(society):
    _setup_flat_and_resident(society)
    _set_hide(society, True)
    client.post("/users/provision-residents", headers=_hdr(society),
                json={"default_password": "shared123"})
    # Bare 10-digit login.
    login = client.post("/auth/login", json={"email": "9555123456", "password": "shared123"})
    assert login.status_code == 200, login.text
    me = client.get("/portal/me", headers={"Authorization": "Bearer " + login.json()["access_token"]})
    assert me.status_code == 200
    assert me.json()["phone"] == PHONE    # own number, unmasked


def test_masking_is_per_society(society):
    # Another society with the toggle OFF keeps full numbers.
    _setup_flat_and_resident(society)
    _set_hide(society, True)
    with system_session() as db:
        other = m.Society(name="PP-Test-Other")
        db.add(other)
        db.flush()
        oid = other.id
        db.add(m.User(id="00000000-0000-0000-0000-0000000000aa", society_id=oid,
                      email="pp2@pp-test.in", password_hash=hash_password("x"), role="society_admin"))
        db.add(m.Wing(society_id=oid, name="A", floors=3, flats_per_floor=2))
        db.flush()
    hdr2 = {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000aa", society_id=str(oid), role="society_admin")}
    client.post("/flats", headers=hdr2, json={"wing_id": str(next(
        w["id"] for w in client.get("/wings", headers=hdr2).json())), "flat_number": "101", "floor": 1})
    client.post("/residents", headers=hdr2,
                json={"flat_number": "A-101", "name": "Other Person", "phone": "+919555999999"})
    rows = client.get("/residents", headers=hdr2).json()
    assert next(r["phone"] for r in rows if r["name"] == "Other Person") == "+919555999999"
