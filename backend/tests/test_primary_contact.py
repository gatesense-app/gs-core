"""
E6-S3 — the agents contact the right person, and rules belong to the door.

This is the only change in the layout epic that can alter a live gate decision,
so these tests are blunt about the two things that matter:

  - resolution is *deterministic* — the same person every time, never "whichever
    row the database returned first";
  - a flat with residents is *never uncontactable*, whatever the admin does.

The eval's shared-flat scenario covers the same ground end-to-end through the
real agents; this covers it cheaply and exhaustively.

    python -m pytest backend/tests/test_primary_contact.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.main import app
from backend.security import create_access_token
from backend.tools import resolve
from backend.tools.gate_tools import GateContext, get_flat_details, get_resident_rules

client = TestClient(app)


def _hdr(society_id, role="society_admin"):
    return {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000c1",
        society_id=str(society_id), role=role)}


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'PRI-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="PRI-Test-Main")
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


# --- Q3: the first resident added is the contact ---------------------------

def test_the_first_resident_of_a_flat_becomes_primary(society):
    first = _add(society, "A-101", "Priya Sharma")
    assert first["is_primary"] is True


def test_a_later_resident_does_not_steal_the_slot(society):
    _add(society, "A-101", "Priya Sharma")
    second = _add(society, "A-101", "Rohit Sharma")
    assert second["is_primary"] is False
    assert _primary_name(society) == "Priya Sharma"


def test_each_flat_gets_its_own_primary(society):
    a = _add(society, "A-101", "Priya Sharma")
    b = _add(society, "A-102", "Arun Mehta")
    assert a["is_primary"] and b["is_primary"]


def test_exactly_one_primary_per_flat_is_enforced_by_the_database(society):
    """Belt and braces: the invariant survives code that forgets it."""
    _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    with pytest.raises(Exception):
        with system_session() as db:
            rohit = db.execute(
                select(m.Resident).where(m.Resident.name == "Rohit Sharma")
            ).scalars().one()
            rohit.is_primary = True   # a second primary for A-101
            db.flush()


def test_the_same_flat_number_in_two_societies_each_have_a_primary(society):
    with system_session() as db:
        other = m.Society(name="PRI-Test-Other")
        db.add(other)
        db.flush()
        other_id = other.id
    assert _add(society, "A-101", "Priya Sharma")["is_primary"] is True
    assert _add(other_id, "A-101", "Someone Else")["is_primary"] is True


# --- Resolution is deterministic -------------------------------------------

def test_the_agents_contact_the_primary_not_an_arbitrary_resident(society):
    """The headline: with a family behind one door, one of them is *the* contact."""
    _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    _add(society, "A-101", "Anjali Sharma")

    with scoped_session(society) as db:
        ctx = GateContext(db, society, None)
        details = get_flat_details(ctx, "A-101")
    assert details["resident_name"] == "Priya Sharma"


def test_resolution_is_stable_across_repeated_reads(society):
    _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    assert len({_primary_name(society) for _ in range(5)}) == 1


def test_a_flat_with_no_primary_flag_still_resolves_deterministically(society):
    """
    Nobody flagged: the oldest resident is the contact. A flat is never left
    uncontactable just because its primary was removed behind the API's back.
    """
    _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    with system_session() as db:
        db.execute(text("UPDATE residents SET is_primary = false "
                        "WHERE society_id = :s"), {"s": str(society)})
    assert _primary_name(society) == "Priya Sharma"


def test_a_vacant_flat_resolves_to_nobody(society):
    with scoped_session(society) as db:
        ctx = GateContext(db, society, None)
        assert get_flat_details(ctx, "Z-999")["resident_name"] == "Unknown"


# --- Changing the primary --------------------------------------------------

def test_an_admin_can_promote_another_resident(society):
    _add(society, "A-101", "Priya Sharma")
    rohit = _add(society, "A-101", "Rohit Sharma")

    r = client.patch(f"/residents/{rohit['id']}", headers=_hdr(society),
                     json={"is_primary": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_primary"] is True
    assert _primary_name(society) == "Rohit Sharma"


def test_promoting_demotes_the_incumbent(society):
    priya = _add(society, "A-101", "Priya Sharma")
    rohit = _add(society, "A-101", "Rohit Sharma")
    client.patch(f"/residents/{rohit['id']}", headers=_hdr(society),
                 json={"is_primary": True})

    got = client.get(f"/residents/{priya['id']}", headers=_hdr(society)).json()
    assert got["is_primary"] is False, "a flat must not end up with two contacts"


def test_demoting_is_refused_because_a_flat_always_needs_a_contact(society):
    priya = _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    r = client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                     json={"is_primary": False})
    assert r.status_code == 422
    assert _primary_name(society) == "Priya Sharma"


def test_moving_the_primary_to_another_flat_resettles_both_doors(society):
    """The door they left keeps a contact; the door they joined doesn't get two."""
    priya = _add(society, "A-101", "Priya Sharma")
    _add(society, "A-101", "Rohit Sharma")
    _add(society, "A-102", "Arun Mehta")

    r = client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                     json={"flat_number": "A-102"})
    assert r.status_code == 200, r.text

    assert _primary_name(society, "A-101") == "Rohit Sharma", "A-101 promoted its survivor"
    assert _primary_name(society, "A-102") == "Arun Mehta", "A-102 kept its own contact"
    assert r.json()["is_primary"] is False


def test_moving_the_only_resident_into_an_empty_flat_keeps_them_primary(society):
    priya = _add(society, "A-101", "Priya Sharma")
    r = client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                     json={"flat_number": "B-201"})
    assert r.status_code == 200
    assert _primary_name(society, "B-201") == "Priya Sharma"
    assert _primary_name(society, "A-101") is None


# --- Rules belong to the door ----------------------------------------------

def _flat_for(society_id, code="A-101"):
    wing = client.post("/wings", headers=_hdr(society_id),
                       json={"name": "A", "floors": 5, "flats_per_floor": 4}).json()
    return client.post("/flats", headers=_hdr(society_id), json={
        "wing_id": wing["id"], "flat_number": code.split("-")[1], "floor": 1}).json()


def test_a_flats_rules_win_over_its_residents(society):
    _add(society, "A-101", "Priya Sharma")
    flat = _flat_for(society)
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "never_allow", "match": "Swiggy"}]})

    with scoped_session(society) as db:
        rules = get_resident_rules(GateContext(db, society, None), "A-101")
    assert rules["standing_rules"] == [{"type": "never_allow", "match": "Swiggy"}]


def test_a_flat_without_rules_falls_back_to_the_primary_contact(society):
    """
    The safety property: introducing a layout must not silently wipe the rules a
    society already had. An unset flat is NOT an empty rule list.
    """
    priya = _add(society, "A-101", "Priya Sharma")
    client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "always_allow", "match": "Swiggy"}]})
    _flat_for(society)  # a flat exists, but states no rules

    with scoped_session(society) as db:
        rules = get_resident_rules(GateContext(db, society, None), "A-101")
    assert rules["standing_rules"] == [{"type": "always_allow", "match": "Swiggy"}]


def test_a_flat_can_explicitly_declare_no_rules(society):
    """[] is a real answer and must not be mistaken for 'unset'."""
    priya = _add(society, "A-101", "Priya Sharma")
    client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "always_allow", "match": "Swiggy"}]})
    flat = _flat_for(society)
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society), json={"standing_rules": []})

    with scoped_session(society) as db:
        rules = get_resident_rules(GateContext(db, society, None), "A-101")
    assert rules["standing_rules"] == [], "the door overrode its residents"


def test_clearing_a_flats_rules_hands_the_door_back_to_its_resident(society):
    priya = _add(society, "A-101", "Priya Sharma")
    client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "always_allow", "match": "Swiggy"}]})
    flat = _flat_for(society)
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society), json={"standing_rules": []})
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society), json={"standing_rules": None})

    with scoped_session(society) as db:
        rules = get_resident_rules(GateContext(db, society, None), "A-101")
    assert rules["standing_rules"] == [{"type": "always_allow", "match": "Swiggy"}]


def test_two_residents_cannot_contradict_each_other_at_one_door(society):
    """
    The reason rules moved to the flat: whoever the agent happened to resolve
    used to decide whether Swiggy got in.
    """
    priya = _add(society, "A-101", "Priya Sharma")
    rohit = _add(society, "A-101", "Rohit Sharma")
    client.patch(f"/residents/{priya['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "always_allow", "match": "Swiggy"}]})
    client.patch(f"/residents/{rohit['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "never_allow", "match": "Swiggy"}]})

    flat = _flat_for(society)
    client.patch(f"/flats/{flat['id']}", headers=_hdr(society),
                 json={"standing_rules": [{"type": "always_allow", "match": "Swiggy"}]})

    with scoped_session(society) as db:
        rules = get_resident_rules(GateContext(db, society, None), "A-101")
    assert rules["standing_rules"] == [{"type": "always_allow", "match": "Swiggy"}]


def test_the_portal_writes_the_doors_rules_when_linked(society):
    """
    A resident editing rules through the portal must change what the gate does.
    Writing to their own row while the agents read the flat's would be a silent
    no-op — the worst kind of bug.
    """
    priya = _add(society, "A-101", "Priya Sharma")
    flat = _flat_for(society)  # links Priya via E4-S4 auto-link

    with system_session() as db:
        user = m.User(society_id=society, email="priya@pri-test.in",
                      password_hash="x", role="resident", resident_id=priya["id"])
        db.add(user)
        db.flush()
        user_id = user.id

    hdr = {"Authorization": "Bearer " + create_access_token(
        user_id=str(user_id), society_id=str(society), role="resident")}
    r = client.patch("/portal/rules", headers=hdr,
                     json={"standing_rules": [{"type": "never_allow", "match": "Zomato"}]})
    assert r.status_code == 200, r.text

    with system_session() as db:
        row = db.get(m.Flat, flat["id"])
        assert row.standing_rules == [{"type": "never_allow", "match": "Zomato"}], \
            "the portal must write the door's rules, not the resident's own"

    with scoped_session(society) as db:
        rules = get_resident_rules(GateContext(db, society, None), "A-101")
    assert rules["standing_rules"] == [{"type": "never_allow", "match": "Zomato"}]
