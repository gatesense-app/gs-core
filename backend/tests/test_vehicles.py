"""
Per-flat vehicle records and parking numbers.

The promises: a flat keeps vehicles (registration number, 2/4-wheeler, RC owner)
and a list of allotted parking numbers; both soft-delete for history and land on
the flat timeline; a registration number / parking number is unique per society;
and none of it crosses a tenant boundary.

    python -m pytest backend/tests/test_vehicles.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend import db_models as m
from backend.deps import system_session
from backend.main import app
from backend.security import create_access_token

client = TestClient(app)

ADMIN_ID = "00000000-0000-0000-0000-0000000000c1"


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'VH-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="VH-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.User(id=ADMIN_ID, society_id=soc.id, email="vh-admin@vh-test.in",
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


def _flat(society_id, number="101"):
    r = client.post("/flats", headers=_hdr(society_id),
                    json={"wing_id": _wing_id(society_id), "flat_number": number, "floor": 1})
    assert r.status_code == 201, r.text
    return r.json()


def _timeline_actions(society_id, flat_id):
    r = client.get(f"/flats/{flat_id}/timeline", headers=_hdr(society_id))
    assert r.status_code == 200, r.text
    return [e["action"] for e in r.json()]


# --- Vehicles ---------------------------------------------------------------

def test_add_edit_remove_a_vehicle_and_record_history(society):
    flat = _flat(society)
    r = client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society),
                    json={"registration_number": "mh12ab1234", "vehicle_type": "four_wheeler",
                          "owner_name": "Ravi Kumar"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["registration_number"] == "MH12AB1234"  # normalised upper-case
    assert v["vehicle_type"] == "four_wheeler"

    # Edit the owner.
    r = client.patch(f"/vehicles/{v['id']}", headers=_hdr(society),
                     json={"owner_name": "Ravi K Kumar"})
    assert r.status_code == 200, r.text
    assert r.json()["owner_name"] == "Ravi K Kumar"

    # Remove (soft).
    assert client.delete(f"/vehicles/{v['id']}", headers=_hdr(society)).status_code == 204
    assert client.get(f"/flats/{flat['id']}/vehicles", headers=_hdr(society)).json() == []

    actions = _timeline_actions(society, flat["id"])
    for a in ("vehicle_added", "vehicle_edited", "vehicle_removed"):
        assert a in actions


def test_two_wheeler_is_supported(society):
    flat = _flat(society)
    r = client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society),
                    json={"registration_number": "KA01X9", "vehicle_type": "two_wheeler",
                          "owner_name": "Asha"})
    assert r.status_code == 201, r.text
    assert r.json()["vehicle_type"] == "two_wheeler"


def test_duplicate_registration_is_refused(society):
    flat = _flat(society)
    body = {"registration_number": "MH12AB1234", "vehicle_type": "four_wheeler", "owner_name": "A"}
    assert client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society), json=body).status_code == 201
    assert client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society), json=body).status_code == 409


def test_a_removed_registration_can_be_re_added(society):
    flat = _flat(society)
    body = {"registration_number": "MH12AB1234", "vehicle_type": "four_wheeler", "owner_name": "A"}
    v = client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society), json=body).json()
    client.delete(f"/vehicles/{v['id']}", headers=_hdr(society))
    # The number is free again once soft-deleted.
    assert client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society), json=body).status_code == 201


# --- Parking ----------------------------------------------------------------

def test_multiple_parking_numbers_per_flat_with_history(society):
    flat = _flat(society)
    for n in ("P-1", "P-2", "P-3"):
        r = client.post(f"/flats/{flat['id']}/parking", headers=_hdr(society),
                        json={"parking_number": n})
        assert r.status_code == 201, r.text
    got = {p["parking_number"] for p in client.get(f"/flats/{flat['id']}/parking", headers=_hdr(society)).json()}
    assert got == {"P-1", "P-2", "P-3"}
    assert _timeline_actions(society, flat["id"]).count("parking_added") == 3


def test_a_parking_number_is_allotted_to_one_flat(society):
    a = _flat(society, "101")
    b = _flat(society, "102")
    assert client.post(f"/flats/{a['id']}/parking", headers=_hdr(society), json={"parking_number": "P-9"}).status_code == 201
    r = client.post(f"/flats/{b['id']}/parking", headers=_hdr(society), json={"parking_number": "P-9"})
    assert r.status_code == 409


def test_releasing_a_parking_number_frees_it(society):
    flat = _flat(society)
    p = client.post(f"/flats/{flat['id']}/parking", headers=_hdr(society), json={"parking_number": "P-1"}).json()
    assert client.delete(f"/parking/{p['id']}", headers=_hdr(society)).status_code == 204
    assert client.post(f"/flats/{flat['id']}/parking", headers=_hdr(society), json={"parking_number": "P-1"}).status_code == 201
    assert "parking_removed" in _timeline_actions(society, flat["id"])


# --- Assigning a vehicle to a parking number --------------------------------

def _add_parking(society_id, flat_id, number):
    r = client.post(f"/flats/{flat_id}/parking", headers=_hdr(society_id),
                    json={"parking_number": number})
    assert r.status_code == 201, r.text
    return r.json()


def test_assign_parking_on_create_and_reassign_on_edit(society):
    flat = _flat(society)
    p1 = _add_parking(society, flat["id"], "P-1")
    p2 = _add_parking(society, flat["id"], "P-2")

    r = client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society),
                    json={"registration_number": "MH12AB1234", "vehicle_type": "four_wheeler",
                          "owner_name": "Ravi", "parking_slot_id": p1["id"]})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["parking_slot_id"] == p1["id"]
    assert v["parking_number"] == "P-1"

    # Reassign to P-2.
    r = client.patch(f"/vehicles/{v['id']}", headers=_hdr(society),
                     json={"parking_slot_id": p2["id"]})
    assert r.json()["parking_number"] == "P-2"

    # Clear the assignment.
    r = client.patch(f"/vehicles/{v['id']}", headers=_hdr(society),
                     json={"parking_slot_id": None})
    assert r.json()["parking_slot_id"] is None
    assert r.json()["parking_number"] is None


def test_cannot_assign_another_flats_parking(society):
    a = _flat(society, "101")
    b = _flat(society, "102")
    p_b = _add_parking(society, b["id"], "P-9")
    r = client.post(f"/flats/{a['id']}/vehicles", headers=_hdr(society),
                    json={"registration_number": "MH01AA1", "vehicle_type": "two_wheeler",
                          "owner_name": "X", "parking_slot_id": p_b["id"]})
    assert r.status_code == 400


def test_releasing_a_parking_number_unassigns_its_vehicle(society):
    flat = _flat(society)
    p = _add_parking(society, flat["id"], "P-1")
    v = client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society),
                    json={"registration_number": "MH12AB1234", "vehicle_type": "four_wheeler",
                          "owner_name": "Ravi", "parking_slot_id": p["id"]}).json()
    assert client.delete(f"/parking/{p['id']}", headers=_hdr(society)).status_code == 204
    # The vehicle survives, but its assignment is cleared.
    got = client.get(f"/flats/{flat['id']}/vehicles", headers=_hdr(society)).json()
    assert len(got) == 1
    assert got[0]["parking_slot_id"] is None
    assert got[0]["parking_number"] is None


# --- Tenancy of the data ----------------------------------------------------

def test_vehicles_do_not_cross_societies(society):
    flat = _flat(society)
    client.post(f"/flats/{flat['id']}/vehicles", headers=_hdr(society),
                json={"registration_number": "MH12AB1234", "vehicle_type": "four_wheeler", "owner_name": "A"})
    with system_session() as db:
        other = m.Society(name="VH-Test-Other")
        db.add(other)
        db.flush()
        other_id = other.id
    other_hdr = {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000c2", society_id=str(other_id), role="society_admin")}
    r = client.get(f"/flats/{flat['id']}/vehicles", headers=other_hdr)
    assert r.status_code == 404, "another society's flat is invisible"
