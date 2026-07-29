"""
Tenancy agreements on tenant-occupied flats.

The promises under test:
  - A tenancy opens only on a tenant-occupied flat, one active at a time.
  - Its primary tenant is who the gate reaches — precedence over the owner.
  - Renewal clones the tenancy (new dates, same people), retires the old one, and
    the old tenants leave the gate but stay on the timeline.
  - Ending a tenancy reverts the flat to owner-occupied and the gate reaches the
    owner again.
  - Dates are optional, and every action lands on the flat's history.

    python -m pytest backend/tests/test_tenancy.py -v
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

ADMIN_ID = "00000000-0000-0000-0000-0000000000f1"


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'TN-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="TN-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.User(id=ADMIN_ID, society_id=soc.id, email="tn-admin@tn-test.in",
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


def _flat(society_id, occupancy="tenant"):
    r = client.post("/flats", headers=_hdr(society_id),
                    json={"wing_id": _wing_id(society_id), "flat_number": "101", "floor": 1})
    assert r.status_code == 201, r.text
    flat = r.json()
    # Every flat has an owner household.
    client.post("/residents", headers=_hdr(society_id),
                json={"flat_number": "A-101", "name": "Olivia Owner"})
    if occupancy == "tenant":
        client.patch(f"/flats/{flat['id']}", headers=_hdr(society_id),
                     json={"occupancy": "tenant"})
    return flat


def _start(society_id, flat_id, **dates):
    r = client.post(f"/flats/{flat_id}/tenancies", headers=_hdr(society_id), json=dates)
    return r


def _add_tenant(society_id, tenancy_id, name):
    r = client.post(f"/tenancies/{tenancy_id}/tenants", headers=_hdr(society_id),
                    json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _primary_name(society_id):
    with scoped_session(society_id) as db:
        p = resolve.primary_resident(db, society_id, "A-101")
        return p.name if p else None


def _timeline_actions(society_id, flat_id):
    r = client.get(f"/flats/{flat_id}/timeline", headers=_hdr(society_id))
    assert r.status_code == 200, r.text
    return [e["action"] for e in r.json()]


# --- Starting ---------------------------------------------------------------

def test_cannot_start_a_tenancy_on_an_owner_occupied_flat(society):
    flat = _flat(society, occupancy="owner")
    r = _start(society, flat["id"])
    assert r.status_code == 409


def test_start_and_one_active_at_a_time(society):
    flat = _flat(society)
    r = _start(society, flat["id"], start_date="2026-01-01", end_date="2026-12-31")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "active"
    # A second active tenancy is refused.
    assert _start(society, flat["id"]).status_code == 409


def test_dates_are_optional(society):
    flat = _flat(society)
    r = _start(society, flat["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["start_date"] is None and body["end_date"] is None


# --- Gate precedence --------------------------------------------------------

def test_primary_tenant_takes_precedence_over_the_owner(society):
    flat = _flat(society)
    t = _start(society, flat["id"]).json()
    _add_tenant(society, t["id"], "Tara Tenant")
    _add_tenant(society, t["id"], "Sam Subtenant")
    # The gate reaches the primary tenant, not the owner.
    assert _primary_name(society) == "Tara Tenant"


# --- Renewal ----------------------------------------------------------------

def test_renew_clones_people_retires_the_old_and_keeps_history(society):
    flat = _flat(society)
    t = _start(society, flat["id"], end_date="2026-06-30").json()
    _add_tenant(society, t["id"], "Tara Tenant")
    _add_tenant(society, t["id"], "Sam Subtenant")

    r = client.post(f"/tenancies/{t['id']}/renew", headers=_hdr(society),
                    json={"start_date": "2026-07-01", "end_date": "2027-06-30"})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != t["id"]
    assert new["prior_tenancy_id"] == t["id"]
    assert new["status"] == "active"
    assert {x["name"] for x in new["tenants"]} == {"Tara Tenant", "Sam Subtenant"}
    # The renewed tenancy still reaches the same primary tenant.
    assert _primary_name(society) == "Tara Tenant"
    # Only one active tenancy remains.
    active = [t2 for t2 in client.get(f"/flats/{flat['id']}/tenancies",
                                      headers=_hdr(society)).json()
              if t2["status"] == "active"]
    assert len(active) == 1
    # The renewal is on the timeline.
    assert "tenancy_renewed" in _timeline_actions(society, flat["id"])


# --- Ending -----------------------------------------------------------------

def test_ending_reverts_to_owner_occupied_and_reaches_the_owner(society):
    flat = _flat(society)
    t = _start(society, flat["id"]).json()
    _add_tenant(society, t["id"], "Tara Tenant")
    assert _primary_name(society) == "Tara Tenant"

    r = client.post(f"/tenancies/{t['id']}/end", headers=_hdr(society))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"

    # Flat is owner-occupied again and the gate reaches the owner.
    flat_after = client.get(f"/flats/{flat['id']}", headers=_hdr(society)).json()
    assert flat_after["occupancy"] == "owner"
    assert _primary_name(society) == "Olivia Owner"

    actions = _timeline_actions(society, flat["id"])
    assert "tenancy_ended" in actions
    assert "flat_occupancy_changed" in actions


def test_a_gate_read_never_sees_an_ended_tenancys_tenant(society):
    flat = _flat(society)
    t = _start(society, flat["id"]).json()
    _add_tenant(society, t["id"], "Tara Tenant")
    client.post(f"/tenancies/{t['id']}/end", headers=_hdr(society))
    with scoped_session(society) as db:
        names = [r.name for r in resolve.flat_residents(db, society, "A-101")]
    assert "Tara Tenant" not in names
    assert "Olivia Owner" in names
