"""
Soft delete + the layout timeline (audit trail).

The two promises: nothing is ever truly removed (a deleted flat or resident keeps
its row and its history), and the flat detail page can replay what happened —
created, renamed, moved, rules changed, residents added/edited/made-primary/
removed — and who did it. The safety half (the gate never resolves a soft-deleted
row) is proven here and in test_layout / test_primary_contact.

    python -m pytest backend/tests/test_timeline.py -v
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

# A real user id so events can snapshot an email.
ADMIN_ID = "00000000-0000-0000-0000-0000000000d1"


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'TL-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    """A society whose admin has a real users row, so actor email is recorded."""
    with system_session() as db:
        soc = m.Society(name="TL-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.User(id=ADMIN_ID, society_id=soc.id, email="tl-admin@tl-test.in",
                      password_hash="x", role="society_admin"))
        db.add(m.Wing(society_id=soc.id, name="A", floors=10, flats_per_floor=4))
        db.flush()
        return soc.id


def _hdr(society_id, role="society_admin", user_id=ADMIN_ID):
    return {"Authorization": "Bearer " + create_access_token(
        user_id=user_id, society_id=str(society_id), role=role)}


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


def _timeline(society_id, flat_id):
    r = client.get(f"/flats/{flat_id}/timeline", headers=_hdr(society_id))
    assert r.status_code == 200, r.text
    return r.json()


def _actions(events):
    return [e["action"] for e in events]


# --- The trail records what happened ---------------------------------------

def test_creating_a_flat_records_an_event_with_the_actor(society):
    flat = _flat(society)
    tl = _timeline(society, flat["id"])
    assert _actions(tl) == ["flat_created"]
    assert tl[0]["actor_email"] == "tl-admin@tl-test.in"
    assert "A-101" in tl[0]["summary"]


def test_edits_accumulate_newest_first(society):
    flat = _flat(society, "101", floor=1)
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society), json={"floor": 3})
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society), json={"flat_number": "102"})
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "always_allow", "match": "Swiggy"}]})

    actions = _actions(_timeline(society, flat["id"]))
    # newest first
    assert actions == ["flat_rules_changed", "flat_renamed", "flat_floor_changed", "flat_created"]


def test_adding_and_removing_a_resident_both_land_on_the_timeline(society):
    flat = _flat(society)
    client.post("/residents", headers=_hdr(society),
                json={"flat_number": "A-101", "name": "Priya Sharma"})
    with system_session() as db:
        rid = str(db.execute(text(
            "SELECT id FROM residents WHERE society_id=:s AND name='Priya Sharma'"),
            {"s": society}).scalar_one())
    client.delete(f"/residents/{rid}", headers=_hdr(society))

    actions = _actions(_timeline(society, flat["id"]))
    assert "resident_added" in actions
    assert "resident_deleted" in actions


def test_deleting_a_flat_records_the_cascade(society):
    flat = _flat(society)
    for name in ("Priya Sharma", "Rohit Sharma"):
        client.post("/residents", headers=_hdr(society),
                    json={"flat_number": "A-101", "name": name})
    client.delete(f"/flats/{flat['id']}", headers=_hdr(society))

    tl = _timeline(society, flat["id"])
    actions = _actions(tl)
    assert actions.count("resident_deleted") == 2
    assert "flat_deleted" in actions
    # The timeline of a deleted flat stays reachable.
    assert client.get(f"/flats/{flat['id']}/timeline", headers=_hdr(society)).status_code == 200


def test_promoting_a_new_contact_after_a_delete_is_recorded(society):
    flat = _flat(society)
    client.post("/residents", headers=_hdr(society),
                json={"flat_number": "A-101", "name": "Priya Sharma"})  # primary
    client.post("/residents", headers=_hdr(society),
                json={"flat_number": "A-101", "name": "Rohit Sharma"})
    with system_session() as db:
        priya = str(db.execute(text(
            "SELECT id FROM residents WHERE society_id=:s AND name='Priya Sharma'"),
            {"s": society}).scalar_one())
    client.delete(f"/residents/{priya}", headers=_hdr(society))

    summaries = [e["summary"] for e in _timeline(society, flat["id"])
                 if e["action"] == "resident_primary_set"]
    assert any("Rohit Sharma" in s for s in summaries), \
        "removing the primary should record who took over"


# --- Nothing leaks to the gate ---------------------------------------------

def test_a_soft_deleted_flats_detail_is_reachable_but_shows_deleted(society):
    flat = _flat(society)
    client.delete(f"/flats/{flat['id']}", headers=_hdr(society))
    r = client.get(f"/flats/{flat['id']}", headers=_hdr(society))
    assert r.status_code == 200
    assert r.json()["deleted_at"] is not None


def test_a_removed_residents_flat_is_never_uncontactable(society):
    """Deleting the primary promotes a live successor the gate can still reach."""
    _flat(society)
    for name in ("Priya Sharma", "Rohit Sharma"):
        client.post("/residents", headers=_hdr(society),
                    json={"flat_number": "A-101", "name": name})
    with system_session() as db:
        priya = str(db.execute(text(
            "SELECT id FROM residents WHERE society_id=:s AND name='Priya Sharma'"),
            {"s": society}).scalar_one())
    client.delete(f"/residents/{priya}", headers=_hdr(society))

    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Rohit Sharma"


# --- Tenancy + roles --------------------------------------------------------

def test_timeline_is_admin_only(society):
    flat = _flat(society)
    for role in ("guard", "resident"):
        r = client.get(f"/flats/{flat['id']}/timeline",
                       headers=_hdr(society, role, user_id="00000000-0000-0000-0000-0000000000ff"))
        assert r.status_code == 403, role


def test_timeline_does_not_cross_societies(society):
    flat = _flat(society)
    with system_session() as db:
        other = m.Society(name="TL-Test-Other")
        db.add(other)
        db.flush()
        other_id = other.id
    r = client.get(f"/flats/{flat['id']}/timeline",
                   headers=_hdr(other_id, user_id="00000000-0000-0000-0000-0000000000fe"))
    assert r.status_code == 404, "another society's flat is invisible"
