"""
E6-S1/S2 — removing a resident (DELETE /residents/{id}).

The two things that matter, mirrored from test_primary_contact.py:

  - a delete never leaves a flat with residents uncontactable — removing the
    primary promotes the deterministic successor;
  - removing the last resident leaves the *flat* present but vacant (we delete
    the person, never the door).

    python -m pytest backend/tests/test_resident_delete.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.main import app
from backend.security import create_access_token
from backend.tools import resolve

client = TestClient(app)


def _hdr(society_id, role="society_admin"):
    return {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000d1",
        society_id=str(society_id), role=role)}


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'DEL-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="DEL-Test-Main")
        db.add(soc)
        db.flush()
        return soc.id


def _add(society_id, flat_number, name):
    r = client.post("/residents", headers=_hdr(society_id),
                    json={"flat_number": flat_number, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _primary_name(society_id, flat_number="A-101"):
    with scoped_session(society_id) as db:
        r = resolve.primary_resident(db, society_id, flat_number)
        return r.name if r else None


def _resident_count(society_id, flat_number="A-101"):
    with scoped_session(society_id) as db:
        return len(resolve.flat_residents(db, society_id, flat_number))


# --- the happy path --------------------------------------------------------

def test_delete_returns_204_and_the_row_is_gone(society):
    priya = _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")

    r = client.delete(f"/residents/{priya['id']}", headers=_hdr(society))
    assert r.status_code == 204, r.text

    got = client.get(f"/residents/{priya['id']}", headers=_hdr(society))
    assert got.status_code == 404


# --- the invariant: never uncontactable ------------------------------------

def test_deleting_the_primary_promotes_a_successor_deterministically(society):
    priya = _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    _add(society, "A-101", "Anjali Sharma")
    assert priya["is_primary"] is True

    r = client.delete(f"/residents/{priya['id']}", headers=_hdr(society))
    assert r.status_code == 204

    # The oldest survivor becomes the contact — the same successor
    # resolve.primary_resident would have fallen back to.
    with scoped_session(society) as db:
        promoted = resolve.primary_resident(db, society, "A-101")
        assert promoted.name == "Rohit Sharma"
        assert promoted.is_primary is True


def test_removing_the_last_resident_leaves_the_flat_present_but_vacant(society):
    # Give the flat a real layout row so we can prove the door survives.
    wing = client.post("/wings", headers=_hdr(society),
                       json={"name": "A", "floors": 5, "flats_per_floor": 4}).json()
    flat = client.post("/flats", headers=_hdr(society), json={
        "wing_id": wing["id"], "flat_number": "101", "floor": 1}).json()

    priya = _add(society, "A-101", "Priya Sharma")
    r = client.delete(f"/residents/{priya['id']}", headers=_hdr(society))
    assert r.status_code == 204

    assert _resident_count(society) == 0
    assert _primary_name(society) is None  # vacant resolves to nobody

    # The flats row is untouched.
    with system_session() as db:
        assert db.get(m.Flat, flat["id"]) is not None


# --- guards -----------------------------------------------------------------

def test_unknown_id_is_404(society):
    r = client.delete("/residents/00000000-0000-0000-0000-0000000000ff",
                      headers=_hdr(society))
    assert r.status_code == 404


def test_a_society_admin_cannot_delete_another_societys_resident(society):
    with system_session() as db:
        other = m.Society(name="DEL-Test-Other")
        db.add(other)
        db.flush()
        other_id = other.id
    victim = _add(other_id, "A-101", "Someone Else")

    # RLS hides the other society's row — it looks absent, not forbidden.
    r = client.delete(f"/residents/{victim['id']}", headers=_hdr(society))
    assert r.status_code == 404

    # And it is genuinely still there.
    with scoped_session(other_id) as db:
        assert db.get(m.Resident, victim["id"]) is not None


def test_a_guard_cannot_delete_a_resident(society):
    priya = _add(society, "A-101", "Priya Sharma")
    r = client.delete(f"/residents/{priya['id']}",
                      headers=_hdr(society, role="guard"))
    assert r.status_code == 403
