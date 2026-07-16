"""
E4-S4 — reconcile existing free-text residents onto flats (D4).

The promise is narrow and absolute: introducing a layout must not orphan anyone.
So the tests that matter are the ones about what *doesn't* happen — nobody is
dropped, nobody is re-pointed on a guess, and the gate keeps working the whole
time (the agents resolve by typed string until E6-S3).

    python -m pytest backend/tests/test_reconcile.py -v
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
    user_id="00000000-0000-0000-0000-0000000000d1", society_id=None, role="platform_admin")}


def _hdr(society_id, role="society_admin"):
    return {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000d2",
        society_id=str(society_id), role=role)}


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'REC-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="REC-Test-Main")
        db.add(soc)
        db.flush()
        return soc.id


@pytest.fixture
def other_society():
    with system_session() as db:
        soc = m.Society(name="REC-Test-Other")
        db.add(soc)
        db.flush()
        return soc.id


def _residents(society_id, *flat_numbers):
    with system_session() as db:
        for i, fn in enumerate(flat_numbers):
            db.add(m.Resident(society_id=society_id, flat_number=fn, name=f"Resident {i}"))
        db.flush()


def _wing(society_id, name="A"):
    r = client.post("/wings", headers=_hdr(society_id),
                    json={"name": name, "floors": 10, "flats_per_floor": 4})
    assert r.status_code == 201, r.text
    return r.json()


def _flat(society_id, wing, number, floor=1):
    r = client.post("/flats", headers=_hdr(society_id),
                    json={"wing_id": wing["id"], "flat_number": number, "floor": floor})
    assert r.status_code == 201, r.text
    return r.json()


class _Row:
    """Plain values: an ORM object detaches once its session closes."""

    def __init__(self, id, flat_id, flat_number):
        self.id = id
        self.flat_id = flat_id
        self.flat_number = flat_number


def _resident_row(society_id, name):
    with system_session() as db:
        r = db.execute(
            select(m.Resident).where(m.Resident.society_id == society_id,
                                     m.Resident.name == name)
        ).scalars().one()
        return _Row(r.id, r.flat_id, r.flat_number)


# --- Auto-link on flat creation -------------------------------------------

def test_a_new_flat_adopts_the_residents_already_on_its_code(society):
    _residents(society, "A-101", "A-101", "A-102")
    wing = _wing(society)
    body = _flat(society, wing, "101")
    # D3: several residents per flat is normal — both get linked.
    assert body["linked_residents"] == 2

    report = client.get("/reconcile", headers=_hdr(society)).json()
    assert report["linked"] == 2
    assert report["unmatched_count"] == 1


def test_a_flat_with_nobody_on_it_links_nobody(society):
    _residents(society, "A-101")
    wing = _wing(society)
    assert _flat(society, wing, "999")["linked_residents"] == 0


def test_a_resident_added_after_the_flat_is_caught_by_run(society):
    """Flat creation adopts who's there at the time; /reconcile/run is the net."""
    wing = _wing(society)
    _flat(society, wing, "101")
    _residents(society, "A-101")

    assert client.get("/reconcile", headers=_hdr(society)).json()["linked"] == 0
    report = client.post("/reconcile/run", headers=_hdr(society)).json()
    assert report["linked"] == 1
    assert report["unmatched_count"] == 0


def test_running_reconcile_twice_changes_nothing(society):
    _residents(society, "A-101")
    wing = _wing(society)
    _flat(society, wing, "101")

    first = client.post("/reconcile/run", headers=_hdr(society)).json()
    before = _resident_row(society, "Resident 0").flat_id
    second = client.post("/reconcile/run", headers=_hdr(society)).json()
    assert first == second
    assert _resident_row(society, "Resident 0").flat_id == before


# --- Nobody is dropped -----------------------------------------------------

def test_unmatched_residents_are_listed_never_dropped(society):
    _residents(society, "A-101", "Cottage 3", "Old Block 7")
    wing = _wing(society)
    _flat(society, wing, "101")

    report = client.post("/reconcile/run", headers=_hdr(society)).json()
    assert report["linked"] == 1
    assert report["unmatched_count"] == 2
    assert {u["flat_number"] for u in report["unmatched"]} == {"Cottage 3", "Old Block 7"}

    # Still there, still resolvable by the string the agents use.
    with system_session() as db:
        assert db.execute(
            select(m.Resident).where(m.Resident.society_id == society)
        ).scalars().all().__len__() == 3


def test_a_near_miss_is_suggested_but_never_auto_linked(society):
    """D2 in spirit: the system doesn't decide `A101` is `A-101` on its own."""
    _residents(society, "A101")
    wing = _wing(society)
    flat = _flat(society, wing, "101")

    report = client.post("/reconcile/run", headers=_hdr(society)).json()
    assert report["linked"] == 0, "a near miss must not be linked automatically"
    assert report["unmatched_count"] == 1
    u = report["unmatched"][0]
    assert u["suggested_flat_id"] == flat["id"]
    assert u["suggested_code"] == "A-101"
    assert _resident_row(society, "Resident 0").flat_id is None


def test_an_ambiguous_near_miss_suggests_nothing(society):
    """
    Wing `A` flat `101` and wing `A1` flat `01` are different flats whose codes
    (`A-101`, `A1-01`) look identical once punctuation is ignored. A machine
    cannot know which one `a 101` meant, so it must not guess.
    """
    _residents(society, "a 101")
    _flat(society, _wing(society, name="A"), "101")    # -> A-101
    _flat(society, _wing(society, name="A1"), "01")    # -> A1-01

    report = client.post("/reconcile/run", headers=_hdr(society)).json()
    assert report["linked"] == 0
    u = report["unmatched"][0]
    assert u["suggested_flat_id"] is None
    assert u["suggested_code"] is None


def test_no_layout_means_everyone_is_unmatched_and_intact(society):
    _residents(society, "A-101", "A-102")
    report = client.get("/reconcile", headers=_hdr(society)).json()
    assert report["flat_count"] == 0
    assert report["linked"] == 0
    assert report["unmatched_count"] == 2


# --- Manual resolution -----------------------------------------------------

def test_manual_link_resolves_a_near_miss_and_keeps_the_gate_working(society):
    """
    The point of the story. `A101` is linked to flat `A-101`, and the resident's
    flat_number becomes the code — so a guard typing `A-101` resolves them.
    Until E6-S3 the agents match on that string, so linking alone isn't enough.
    """
    _residents(society, "A101")
    wing = _wing(society)
    flat = _flat(society, wing, "101")
    resident = _resident_row(society, "Resident 0")

    r = client.post("/reconcile/link", headers=_hdr(society),
                    json={"resident_id": str(resident.id), "flat_id": flat["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["linked"] == 1
    assert r.json()["unmatched_count"] == 0

    after = _resident_row(society, "Resident 0")
    assert str(after.flat_id) == flat["id"]
    assert after.flat_number == "A-101", "the guard's typed code must now find them"


def test_manual_link_does_not_touch_visitor_history(society):
    """`visitor_sessions.flat_number` is a snapshot of what was typed then."""
    _residents(society, "A101")
    wing = _wing(society)
    flat = _flat(society, wing, "101")
    with system_session() as db:
        db.add(m.VisitorSession(society_id=society, visitor_name="Amit",
                                flat_number="A101", purpose="guest"))
        db.flush()

    resident = _resident_row(society, "Resident 0")
    client.post("/reconcile/link", headers=_hdr(society),
                json={"resident_id": str(resident.id), "flat_id": flat["id"]})

    with system_session() as db:
        session = db.execute(
            select(m.VisitorSession).where(m.VisitorSession.society_id == society)
        ).scalars().one()
        assert session.flat_number == "A101", "history must stay meaningful"


def test_manual_link_to_an_unknown_flat_or_resident_is_404(society):
    _residents(society, "A101")
    wing = _wing(society)
    flat = _flat(society, wing, "101")
    resident = _resident_row(society, "Resident 0")
    ghost = "00000000-0000-0000-0000-0000000000ff"

    assert client.post("/reconcile/link", headers=_hdr(society),
                       json={"resident_id": ghost, "flat_id": flat["id"]}).status_code == 404
    assert client.post("/reconcile/link", headers=_hdr(society),
                       json={"resident_id": str(resident.id), "flat_id": ghost}).status_code == 404


# --- Tenancy + roles -------------------------------------------------------

def test_reconcile_never_reaches_across_societies(society, other_society):
    _residents(society, "A-101")
    _residents(other_society, "A-101")
    wing = _wing(society)
    body = _flat(society, wing, "101")

    assert body["linked_residents"] == 1, "only this society's resident is adopted"
    with system_session() as db:
        theirs = db.execute(
            select(m.Resident).where(m.Resident.society_id == other_society)
        ).scalars().one()
        assert theirs.flat_id is None, "another society's resident must be untouched"


def test_a_society_admin_cannot_link_across_societies(society, other_society):
    _residents(other_society, "A-101")
    wing = _wing(society)
    flat = _flat(society, wing, "101")
    theirs = _resident_row(other_society, "Resident 0")

    r = client.post("/reconcile/link", headers=_hdr(society),
                    json={"resident_id": str(theirs.id), "flat_id": flat["id"]})
    assert r.status_code == 404, "RLS hides the foreign resident entirely"


def test_platform_admin_cannot_link_a_resident_to_another_societys_flat(society, other_society):
    """A platform_admin bypasses RLS, so this needs an explicit check."""
    _residents(other_society, "A-101")
    wing = _wing(society)
    flat = _flat(society, wing, "101")
    theirs = _resident_row(other_society, "Resident 0")

    r = client.post("/reconcile/link", headers=PLATFORM,
                    json={"resident_id": str(theirs.id), "flat_id": flat["id"]})
    assert r.status_code == 400


def test_platform_admin_must_name_a_society(society):
    assert client.get("/reconcile", headers=PLATFORM).status_code == 422
    r = client.get(f"/reconcile?society_id={society}", headers=PLATFORM)
    assert r.status_code == 200


def test_guards_and_residents_cannot_reconcile(society):
    for role in ("guard", "resident"):
        assert client.get("/reconcile", headers=_hdr(society, role)).status_code == 403
        assert client.post("/reconcile/run", headers=_hdr(society, role)).status_code == 403
