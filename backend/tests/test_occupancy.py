"""
Owner vs tenant occupancy, and who the gate reaches.

The rules under test:
  - The first resident on a flat is its owner; everyone added after is a tenant.
  - A flat is owner- or tenant-occupied. Occupancy decides which role the gate's
    primary contact is drawn from — a tenant-occupied flat reaches a tenant, an
    owner-occupied one reaches the owner.
  - A tenant-occupied flat with no tenant yet still reaches its owner (never
    uncontactable).
  - Every occupancy flip and role change lands on the flat's timeline.

    python -m pytest backend/tests/test_occupancy.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.main import app
from backend.security import create_access_token
from backend.tools import resolve

client = TestClient(app)

ADMIN_ID = "00000000-0000-0000-0000-0000000000e1"


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'OC-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="OC-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.User(id=ADMIN_ID, society_id=soc.id, email="oc-admin@oc-test.in",
                      password_hash="x", role="society_admin"))
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


def _flat(society_id, number="101", floor=1):
    r = client.post("/flats", headers=_hdr(society_id),
                    json={"wing_id": _wing_id(society_id), "flat_number": number, "floor": floor})
    assert r.status_code == 201, r.text
    return r.json()


def _add(society_id, name, role=None):
    body = {"flat_number": "A-101", "name": name}
    if role:
        body["role"] = role
    r = client.post("/residents", headers=_hdr(society_id), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _residents(society_id):
    r = client.get("/residents", headers=_hdr(society_id))
    return {x["name"]: x for x in r.json()}


def _set_occupancy(society_id, flat_id, value):
    r = client.patch(f"/flats/{flat_id}", headers=_hdr(society_id), json={"occupancy": value})
    assert r.status_code == 200, r.text
    return r.json()


def _timeline_actions(society_id, flat_id):
    r = client.get(f"/flats/{flat_id}/timeline", headers=_hdr(society_id))
    assert r.status_code == 200, r.text
    return [e["action"] for e in r.json()]


# --- Role assignment --------------------------------------------------------

def test_residents_default_to_owner(society):
    # Residents added on the flat are the owners/household; tenants come only
    # through a tenancy (see test_tenancy.py).
    _flat(society)
    a = _add(society, "Priya Sharma")
    b = _add(society, "Rahul Verma")
    assert a["role"] == "owner"
    assert b["role"] == "owner"


def test_flat_defaults_to_owner_occupied(society):
    flat = _flat(society)
    assert flat["occupancy"] == "owner"


# --- Occupancy decides the gate contact ------------------------------------

def test_owner_occupied_flat_reaches_the_owner(society):
    _flat(society)
    _add(society, "Priya Sharma")          # owner
    _add(society, "Tina Tenant", role="tenant")
    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Priya Sharma"


def test_tenant_occupied_flat_reaches_a_tenant(society):
    flat = _flat(society)
    _add(society, "Priya Sharma")          # owner
    _add(society, "Tina Tenant", role="tenant")
    _set_occupancy(society, flat["id"], "tenant")
    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Tina Tenant"


def test_tenant_occupied_but_no_tenant_still_reaches_the_owner(society):
    flat = _flat(society)
    _add(society, "Priya Sharma")          # owner only
    _set_occupancy(society, flat["id"], "tenant")
    with scoped_session(society) as db:
        # Never uncontactable: falls back to the owner when no tenant exists.
        assert resolve.primary_resident(db, society, "A-101").name == "Priya Sharma"


def test_owner_keeps_the_owner_label_even_when_a_tenant_is_contacted(society):
    flat = _flat(society)
    _add(society, "Priya Sharma")
    _add(society, "Tina Tenant", role="tenant")
    _set_occupancy(society, flat["id"], "tenant")
    residents = _residents(society)
    assert residents["Priya Sharma"]["role"] == "owner"
    assert residents["Priya Sharma"]["is_primary"] is False
    assert residents["Tina Tenant"]["is_primary"] is True


def test_flipping_back_to_owner_restores_the_owner_as_contact(society):
    flat = _flat(society)
    _add(society, "Priya Sharma")
    _add(society, "Tina Tenant", role="tenant")
    _set_occupancy(society, flat["id"], "tenant")
    _set_occupancy(society, flat["id"], "owner")
    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Priya Sharma"


# --- History ----------------------------------------------------------------

def test_occupancy_change_is_recorded(society):
    flat = _flat(society)
    _add(society, "Priya Sharma")
    _add(society, "Tina Tenant", role="tenant")
    _set_occupancy(society, flat["id"], "tenant")
    actions = _timeline_actions(society, flat["id"])
    assert "flat_occupancy_changed" in actions
    # The contact hand-over to the tenant is recorded too.
    assert "resident_primary_set" in actions


def test_role_change_is_recorded(society):
    flat = _flat(society)
    priya = _add(society, "Priya Sharma")
    r = client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                     json={"role": "tenant"})
    assert r.status_code == 200, r.text
    assert "resident_role_changed" in _timeline_actions(society, flat["id"])
