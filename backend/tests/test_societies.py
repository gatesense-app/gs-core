"""
Society lifecycle (E1) and the admin-allocation stories (E1-S2 / E2-S1).

E1-S2 and E2-S1 needed no new code — the existing POST /users already allocates
society admins. These tests pin that behaviour down so it can't regress, and
prove the tenancy rule that makes it safe: a society_admin can never plant an
admin in someone else's society.

    python -m pytest backend/tests/test_societies.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token

client = TestClient(app)

PLATFORM = {"Authorization": "Bearer " + create_access_token(
    user_id="00000000-0000-0000-0000-0000000000f1", society_id=None, role="platform_admin")}


def _society_admin_hdr(society_id):
    return {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000f2",
        society_id=str(society_id), role="society_admin")}


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'SOC-Test%'"))
            db.execute(text("DELETE FROM users WHERE email LIKE '%@soc-test.in'"))
    purge()
    yield
    purge()


@pytest.fixture
def other_society():
    with system_session() as db:
        soc = m.Society(name="SOC-Test-Other")
        db.add(soc)
        db.flush()
        return soc.id


# --- E1-S1: create without an admin ---------------------------------------

def test_create_society_without_an_admin(other_society):
    r = client.post("/societies", headers=PLATFORM,
                    json={"name": "SOC-Test-Adminless", "address": "MG Road"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "SOC-Test-Adminless"
    # Visible in the list as having nobody to run it.
    assert body["admin_count"] == 0


def test_create_society_with_an_admin_still_works(other_society):
    r = client.post("/societies", headers=PLATFORM, json={
        "name": "SOC-Test-WithAdmin", "address": "Baner",
        "admin_email": "first@soc-test.in", "admin_password": "password123",
        "admin_name": "First Admin",
    })
    assert r.status_code == 201, r.text
    assert r.json()["admin_count"] == 1

    with system_session() as db:
        u = db.execute(select(m.User).where(m.User.email == "first@soc-test.in")).scalars().first()
        assert u is not None and u.role == "society_admin"


def test_half_an_admin_is_rejected(other_society):
    """An email with no password would create an 'admin' who can never sign in."""
    r = client.post("/societies", headers=PLATFORM, json={
        "name": "SOC-Test-Half", "admin_email": "half@soc-test.in"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"

    # ...and the society was not created as a side effect.
    with system_session() as db:
        assert db.execute(
            select(m.Society).where(m.Society.name == "SOC-Test-Half")
        ).scalars().first() is None


def test_duplicate_admin_email_does_not_leave_a_society_behind():
    client.post("/societies", headers=PLATFORM, json={
        "name": "SOC-Test-Dup1", "admin_email": "dup@soc-test.in", "admin_password": "password123"})
    r = client.post("/societies", headers=PLATFORM, json={
        "name": "SOC-Test-Dup2", "admin_email": "dup@soc-test.in", "admin_password": "password123"})
    assert r.status_code == 409
    with system_session() as db:
        assert db.execute(
            select(m.Society).where(m.Society.name == "SOC-Test-Dup2")
        ).scalars().first() is None, "the society must not survive a failed admin creation"


def test_only_platform_admin_creates_societies(other_society):
    r = client.post("/societies", headers=_society_admin_hdr(other_society),
                    json={"name": "SOC-Test-Nope"})
    assert r.status_code == 403


# --- E1-S2: allocate an admin at any time (already supported) --------------

def test_platform_admin_allocates_an_admin_to_an_existing_society():
    r = client.post("/societies", headers=PLATFORM, json={"name": "SOC-Test-Late"})
    sid = r.json()["id"]
    assert r.json()["admin_count"] == 0

    # No new endpoint needed: POST /users targets any society for a platform admin.
    r = client.post("/users", headers=PLATFORM, json={
        "email": "late@soc-test.in", "password": "password123",
        "role": "society_admin", "full_name": "Late Admin", "society_id": sid})
    assert r.status_code == 201, r.text
    assert r.json()["society_id"] == sid

    assert next(s for s in client.get("/societies", headers=PLATFORM).json()
                if s["id"] == sid)["admin_count"] == 1


def test_a_society_can_have_several_admins():
    sid = client.post("/societies", headers=PLATFORM, json={"name": "SOC-Test-Many"}).json()["id"]
    for i in range(3):
        r = client.post("/users", headers=PLATFORM, json={
            "email": f"many{i}@soc-test.in", "password": "password123",
            "role": "society_admin", "society_id": sid})
        assert r.status_code == 201
    assert next(s for s in client.get("/societies", headers=PLATFORM).json()
                if s["id"] == sid)["admin_count"] == 3


# --- E2-S1: a society admin can add another, in THEIR society only ---------

def test_society_admin_can_add_another_society_admin():
    sid = client.post("/societies", headers=PLATFORM, json={"name": "SOC-Test-Peer"}).json()["id"]
    r = client.post("/users", headers=_society_admin_hdr(sid), json={
        "email": "peer@soc-test.in", "password": "password123", "role": "society_admin"})
    assert r.status_code == 201, r.text
    assert r.json()["society_id"] == sid


def test_society_admin_cannot_plant_an_admin_in_another_society(other_society):
    """The tenancy rule that makes E2-S1 safe: a client-supplied society_id is ignored."""
    mine = client.post("/societies", headers=PLATFORM, json={"name": "SOC-Test-Mine"}).json()["id"]

    r = client.post("/users", headers=_society_admin_hdr(mine), json={
        "email": "intruder@soc-test.in", "password": "password123",
        "role": "society_admin",
        "society_id": str(other_society),      # <- attempt to target someone else
    })
    assert r.status_code == 201
    assert r.json()["society_id"] == mine, "society_id must come from the JWT, not the body"

    with system_session() as db:
        u = db.execute(select(m.User).where(m.User.email == "intruder@soc-test.in")).scalars().first()
        assert str(u.society_id) != str(other_society)


# --- E1-S3: modify a society ----------------------------------------------

def test_platform_admin_updates_a_society():
    sid = client.post("/societies", headers=PLATFORM,
                      json={"name": "SOC-Test-Old", "address": "Old Road"}).json()["id"]

    r = client.patch(f"/societies/{sid}", headers=PLATFORM,
                     json={"name": "SOC-Test-New", "address": "New Road"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "SOC-Test-New"
    assert r.json()["address"] == "New Road"

    assert next(s for s in client.get("/societies", headers=PLATFORM).json()
                if s["id"] == sid)["name"] == "SOC-Test-New"


def test_partial_update_leaves_other_fields_alone():
    sid = client.post("/societies", headers=PLATFORM,
                      json={"name": "SOC-Test-Partial", "address": "Keep Me"}).json()["id"]
    r = client.patch(f"/societies/{sid}", headers=PLATFORM, json={"name": "SOC-Test-Renamed"})
    assert r.status_code == 200
    assert r.json()["address"] == "Keep Me"


def test_update_does_not_touch_residents_or_users():
    sid = client.post("/societies", headers=PLATFORM, json={
        "name": "SOC-Test-Intact", "admin_email": "intact@soc-test.in",
        "admin_password": "password123"}).json()["id"]
    with system_session() as db:
        db.add(m.Resident(society_id=sid, flat_number="A-101", name="Priya Sharma"))
        db.flush()

    client.patch(f"/societies/{sid}", headers=PLATFORM, json={"name": "SOC-Test-Intact2"})

    with system_session() as db:
        assert db.execute(select(m.Resident).where(m.Resident.society_id == sid)).scalars().first() is not None
        assert db.execute(select(m.User).where(m.User.email == "intact@soc-test.in")).scalars().first() is not None


def test_society_admin_cannot_update_a_society(other_society):
    r = client.patch(f"/societies/{other_society}", headers=_society_admin_hdr(other_society),
                     json={"name": "SOC-Test-Hacked"})
    assert r.status_code == 403


def test_update_unknown_society_is_404():
    r = client.patch("/societies/00000000-0000-0000-0000-0000000000ff",
                     headers=PLATFORM, json={"name": "SOC-Test-Ghost"})
    assert r.status_code == 404


def test_empty_update_is_rejected(other_society):
    r = client.patch(f"/societies/{other_society}", headers=PLATFORM, json={})
    assert r.status_code == 422
