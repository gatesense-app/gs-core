"""
Society layout — E4-S1 (declare a wing) and E4-S2 (add a flat).

The load-bearing claims here are the ones that would be expensive to discover
later: codes are typed and never generated (D2), floor is stored and never
parsed (Q1), the declared shape only warns (Q2), totals are counted from real
flats, and neither wings nor flats leak across societies.

    python -m pytest backend/tests/test_layout.py -v
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
    user_id="00000000-0000-0000-0000-0000000000e1", society_id=None, role="platform_admin")}


def _hdr(society_id, role="society_admin"):
    return {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000e2",
        society_id=str(society_id), role=role)}


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'LAY-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    with system_session() as db:
        soc = m.Society(name="LAY-Test-Main")
        db.add(soc)
        db.flush()
        return soc.id


@pytest.fixture
def other_society():
    with system_session() as db:
        soc = m.Society(name="LAY-Test-Other")
        db.add(soc)
        db.flush()
        return soc.id


def _wing(society_id, name="A", floors=10, per_floor=4):
    r = client.post("/wings", headers=_hdr(society_id),
                    json={"name": name, "floors": floors, "flats_per_floor": per_floor})
    assert r.status_code == 201, r.text
    return r.json()


# --- E4-S1: declare a wing -------------------------------------------------

def test_declaring_a_wing_creates_no_flats(society):
    body = _wing(society, name="A", floors=10, per_floor=4)
    assert body["name"] == "A"
    assert body["floors"] == 10 and body["flats_per_floor"] == 4
    # D2: the grid is declared; the flats are not conjured.
    assert body["flat_count"] == 0
    with system_session() as db:
        assert db.execute(
            select(m.Flat).where(m.Flat.society_id == society)
        ).scalars().all() == []


def test_wings_in_one_society_may_have_different_shapes(society):
    _wing(society, name="A", floors=10, per_floor=4)
    _wing(society, name="B", floors=3, per_floor=8)
    rows = client.get("/wings", headers=_hdr(society)).json()
    assert {(w["name"], w["floors"], w["flats_per_floor"]) for w in rows} == {
        ("A", 10, 4), ("B", 3, 8)}


def test_duplicate_wing_name_is_rejected(society):
    _wing(society, name="A")
    r = client.post("/wings", headers=_hdr(society),
                    json={"name": "A", "floors": 5, "flats_per_floor": 2})
    assert r.status_code == 409
    assert "already exists" in r.json()["error"]["message"]


def test_same_wing_name_in_a_different_society_is_fine(society, other_society):
    """Uniqueness is per society — half the properties in India have a wing 'A'."""
    _wing(society, name="A")
    _wing(other_society, name="A")


def test_platform_admin_must_name_a_society(society):
    r = client.post("/wings", headers=PLATFORM,
                    json={"name": "A", "floors": 5, "flats_per_floor": 2})
    assert r.status_code == 422

    r = client.post("/wings", headers=PLATFORM, json={
        "name": "A", "floors": 5, "flats_per_floor": 2, "society_id": str(society)})
    assert r.status_code == 201, r.text
    assert r.json()["society_id"] == str(society)


def test_society_admin_cannot_plant_a_wing_in_another_society(society, other_society):
    r = client.post("/wings", headers=_hdr(society), json={
        "name": "Intruder", "floors": 5, "flats_per_floor": 2,
        "society_id": str(other_society),  # <- ignored: society_id comes from the JWT
    })
    assert r.status_code == 201
    assert r.json()["society_id"] == str(society)


def test_wings_do_not_leak_across_societies(society, other_society):
    _wing(society, name="Mine")
    _wing(other_society, name="Theirs")
    names = [w["name"] for w in client.get("/wings", headers=_hdr(society)).json()]
    assert names == ["Mine"]


def test_guards_and_residents_cannot_declare_wings(society):
    for role in ("guard", "resident"):
        r = client.post("/wings", headers=_hdr(society, role),
                        json={"name": "Nope", "floors": 5, "flats_per_floor": 2})
        assert r.status_code == 403, role


def test_society_total_flats_is_counted_not_derived(society):
    """Q2: floors * flats_per_floor would claim 40 flats where 1 exists."""
    wing = _wing(society, name="A", floors=10, per_floor=4)
    assert _society_row(society)["flat_count"] == 0

    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    assert _society_row(society)["flat_count"] == 1


def _society_row(society_id):
    rows = client.get("/societies", headers=PLATFORM).json()
    return next(s for s in rows if s["id"] == str(society_id))


# --- E4-S3: edit a wing after the fact -------------------------------------

def test_renaming_a_wing_does_not_rewrite_existing_flat_codes(society):
    """
    The rule this story exists for. `visitor_sessions.flat_number` is the string
    a guard typed at the time, and the agents still resolve residents by it —
    rewriting A-101 to B-101 would retitle history that already happened.
    """
    wing = _wing(society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})

    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "B"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "B"

    codes = [f["code"] for f in client.get("/flats", headers=_hdr(society)).json()]
    assert codes == ["A-101"], "the existing flat keeps the code history knows it by"


def test_a_renamed_wings_new_flats_use_the_new_name(society):
    wing = _wing(society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "B"})

    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": "102", "floor": 1})
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "B-102"

    codes = sorted(f["code"] for f in client.get("/flats", headers=_hdr(society)).json())
    assert codes == ["A-101", "B-102"], "old codes stay, new ones take the new name"


def test_renaming_leaves_visitor_history_meaningful(society):
    wing = _wing(society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    with system_session() as db:
        db.add(m.VisitorSession(society_id=society, visitor_name="Amit",
                                flat_number="A-101", purpose="guest"))
        db.flush()

    client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "B"})

    with system_session() as db:
        session = db.execute(
            select(m.VisitorSession).where(m.VisitorSession.society_id == society)
        ).scalars().one()
        assert session.flat_number == "A-101"


def test_renaming_says_which_codes_it_kept(society):
    """A silent rename would look like the codes had followed the name."""
    wing = _wing(society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "B"})
    assert any("A-101" in w and "keep their codes" in w for w in r.json()["warnings"])


def test_renaming_an_empty_wing_warns_about_nothing(society):
    wing = _wing(society, name="A")
    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "B"})
    assert r.json()["warnings"] == []


def test_renaming_to_an_existing_name_is_rejected(society):
    _wing(society, name="A")
    b = _wing(society, name="B")
    r = client.patch(f"/wings/{b['id']}", headers=_hdr(society), json={"name": "A"})
    assert r.status_code == 409
    assert client.get(f"/wings/{b['id']}", headers=_hdr(society)).json()["name"] == "B"


def test_renaming_a_wing_to_its_own_name_is_fine(society):
    wing = _wing(society, name="A")
    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "A"})
    assert r.status_code == 200
    assert r.json()["name"] == "A"


def test_the_same_new_name_in_another_society_is_fine(society, other_society):
    _wing(other_society, name="B")
    wing = _wing(society, name="A")
    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"name": "B"})
    assert r.status_code == 200


def test_changing_the_shape_only_redraws_the_grid(society):
    wing = _wing(society, name="A", floors=10, per_floor=4)
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})

    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society),
                     json={"floors": 3, "flats_per_floor": 8})
    assert r.status_code == 200
    assert (r.json()["floors"], r.json()["flats_per_floor"]) == (3, 8)

    flats = client.get("/flats", headers=_hdr(society)).json()
    assert len(flats) == 1 and flats[0]["code"] == "A-101" and flats[0]["floor"] == 1


def test_reducing_the_shape_never_deletes_flats(society):
    """Q2: the shape is a hint. Shrinking it below reality keeps every flat."""
    wing = _wing(society, name="A", floors=10, per_floor=4)
    for n, fl in (("101", 1), ("102", 1), ("901", 9)):
        client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": n, "floor": fl})

    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society),
                     json={"floors": 2, "flats_per_floor": 1})
    assert r.status_code == 200, r.text
    assert r.json()["flat_count"] == 3, "not one flat was removed"
    assert len(client.get("/flats", headers=_hdr(society)).json()) == 3

    warnings = " ".join(r.json()["warnings"])
    assert "above the 2 floor(s)" in warnings   # A-901 is outside the new height
    assert "more than the 1 flat(s)" in warnings  # floor 1 holds two


def test_a_shape_that_still_fits_warns_about_nothing(society):
    wing = _wing(society, name="A", floors=10, per_floor=4)
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={"floors": 5})
    assert r.json()["warnings"] == []


def test_empty_wing_update_is_rejected(society):
    wing = _wing(society, name="A")
    assert client.patch(f"/wings/{wing['id']}", headers=_hdr(society), json={}).status_code == 422


def test_a_zero_floor_wing_is_rejected(society):
    wing = _wing(society, name="A")
    assert client.patch(f"/wings/{wing['id']}", headers=_hdr(society),
                        json={"floors": 0}).status_code == 422


def test_society_admin_cannot_edit_another_societys_wing(society, other_society):
    theirs = _wing(other_society, name="Theirs")
    r = client.patch(f"/wings/{theirs['id']}", headers=_hdr(society), json={"name": "Mine"})
    assert r.status_code == 404, "RLS hides it entirely"


def test_editing_an_unknown_wing_is_404(society):
    r = client.patch("/wings/00000000-0000-0000-0000-0000000000ff",
                     headers=_hdr(society), json={"name": "Ghost"})
    assert r.status_code == 404


def test_guards_and_residents_cannot_edit_wings(society):
    wing = _wing(society, name="A")
    for role in ("guard", "resident"):
        r = client.patch(f"/wings/{wing['id']}", headers=_hdr(society, role),
                         json={"name": "Nope"})
        assert r.status_code == 403, role


# --- E4-S2: add a flat -----------------------------------------------------

def test_flat_code_is_wing_plus_typed_number(society):
    wing = _wing(society, name="A")
    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"] == "A-101"
    assert body["flat_number"] == "101"
    assert body["floor"] == 1
    assert body["warnings"] == []


def test_floor_is_stored_not_parsed_from_the_code(society):
    """Q1: `101` on floor 7 is a real thing an admin can type, and must stick."""
    wing = _wing(society, name="A")
    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": "101", "floor": 7})
    assert r.status_code == 201
    assert r.json()["floor"] == 7, "floor must be the one given, not derived from '101'"

    with system_session() as db:
        # Scoped to this society: system_session bypasses RLS, so an unscoped
        # code lookup would also match any other society's A-101.
        flat = db.execute(select(m.Flat).where(
            m.Flat.society_id == society, m.Flat.code == "A-101")).scalars().one()
        assert flat.floor == 7


def test_a_code_that_looks_nothing_like_a_grid_is_accepted(society):
    """D2: the code is whatever is painted on the door."""
    wing = _wing(society, name="Tower")
    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": "PH-Duplex", "floor": 11})
    assert r.status_code == 201
    assert r.json()["code"] == "Tower-PH-Duplex"


def test_duplicate_flat_code_is_rejected(society):
    wing = _wing(society, name="A")
    payload = {"wing_id": wing["id"], "flat_number": "101", "floor": 1}
    assert client.post("/flats", headers=_hdr(society), json=payload).status_code == 201
    r = client.post("/flats", headers=_hdr(society), json=payload)
    assert r.status_code == 409
    assert "A-101" in r.json()["error"]["message"]


def test_the_same_number_in_two_wings_is_not_a_duplicate(society):
    a = _wing(society, name="A")
    b = _wing(society, name="B")
    for wing in (a, b):
        r = client.post("/flats", headers=_hdr(society),
                        json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
        assert r.status_code == 201
    codes = {f["code"] for f in client.get("/flats", headers=_hdr(society)).json()}
    assert codes == {"A-101", "B-101"}


def test_exceeding_flats_per_floor_warns_and_saves(society):
    """Q2: the declared shape is a hint. Ground-floor shops are not an error."""
    wing = _wing(society, name="A", floors=10, per_floor=2)
    for n in ("101", "102"):
        r = client.post("/flats", headers=_hdr(society),
                        json={"wing_id": wing["id"], "flat_number": n, "floor": 1})
        assert r.status_code == 201
        assert r.json()["warnings"] == []

    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": "103", "floor": 1})
    assert r.status_code == 201, "a third flat on the floor must SAVE, not fail"
    assert r.json()["warnings"], "...but it must say something"
    assert "3 flats" in r.json()["warnings"][0]
    assert client.get(f"/wings/{wing['id']}", headers=_hdr(society)).json()["flat_count"] == 3


def test_a_floor_above_the_declared_height_warns_and_saves(society):
    wing = _wing(society, name="A", floors=2, per_floor=4)
    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": "301", "floor": 3})
    assert r.status_code == 201
    assert any("above" in w for w in r.json()["warnings"])


def test_flat_count_reflects_real_flats(society):
    wing = _wing(society, name="A", floors=10, per_floor=4)
    for n in ("101", "102"):
        client.post("/flats", headers=_hdr(society),
                    json={"wing_id": wing["id"], "flat_number": n, "floor": 1})
    # Not 40 (10 * 4) — two.
    assert client.get("/wings", headers=_hdr(society)).json()[0]["flat_count"] == 2


def test_flats_do_not_leak_across_societies(society, other_society):
    mine = _wing(society, name="A")
    theirs = _wing(other_society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": mine["id"], "flat_number": "101", "floor": 1})
    client.post("/flats", headers=_hdr(other_society),
                json={"wing_id": theirs["id"], "flat_number": "999", "floor": 9})

    numbers = [f["flat_number"] for f in client.get("/flats", headers=_hdr(society)).json()]
    assert numbers == ["101"]


def test_cannot_add_a_flat_to_another_societys_wing(society, other_society):
    """The wing is resolved through RLS, so a foreign wing_id is simply not found."""
    theirs = _wing(other_society, name="Theirs")
    r = client.post("/flats", headers=_hdr(society),
                    json={"wing_id": theirs["id"], "flat_number": "101", "floor": 1})
    assert r.status_code == 404


def test_guards_and_residents_cannot_add_flats(society):
    wing = _wing(society, name="A")
    for role in ("guard", "resident"):
        r = client.post("/flats", headers=_hdr(society, role),
                        json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
        assert r.status_code == 403, role


def test_flat_on_an_unknown_wing_is_404(society):
    r = client.post("/flats", headers=_hdr(society), json={
        "wing_id": "00000000-0000-0000-0000-0000000000ff", "flat_number": "1", "floor": 1})
    assert r.status_code == 404


# --- Deleting: never silently drop something occupied ----------------------

def test_deleting_a_flat_with_residents_is_refused(society):
    wing = _wing(society, name="A")
    flat = client.post("/flats", headers=_hdr(society),
                       json={"wing_id": wing["id"], "flat_number": "101", "floor": 1}).json()
    with system_session() as db:
        db.add(m.Resident(society_id=society, flat_number="A-101",
                          name="Priya Sharma", flat_id=flat["id"]))
        db.flush()

    r = client.delete(f"/flats/{flat['id']}", headers=_hdr(society))
    assert r.status_code == 409
    assert client.get(f"/flats/{flat['id']}", headers=_hdr(society)).status_code == 200


def test_deleting_a_flat_with_visitor_history_is_refused(society):
    wing = _wing(society, name="A")
    flat = client.post("/flats", headers=_hdr(society),
                       json={"wing_id": wing["id"], "flat_number": "101", "floor": 1}).json()
    with system_session() as db:
        db.add(m.VisitorSession(society_id=society, visitor_name="Amit",
                                flat_number="A-101", purpose="guest"))
        db.flush()

    assert client.delete(f"/flats/{flat['id']}", headers=_hdr(society)).status_code == 409


def test_an_empty_flat_can_be_deleted(society):
    wing = _wing(society, name="A")
    flat = client.post("/flats", headers=_hdr(society),
                       json={"wing_id": wing["id"], "flat_number": "101", "floor": 1}).json()
    assert client.delete(f"/flats/{flat['id']}", headers=_hdr(society)).status_code == 204
    assert client.get("/flats", headers=_hdr(society)).json() == []


def test_deleting_a_wing_with_flats_is_refused(society):
    """The FK cascade would take occupied flats with it — not silently."""
    wing = _wing(society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})
    r = client.delete(f"/wings/{wing['id']}", headers=_hdr(society))
    assert r.status_code == 409
    assert client.get(f"/wings/{wing['id']}", headers=_hdr(society)).status_code == 200


def test_an_empty_wing_can_be_deleted(society):
    wing = _wing(society, name="A")
    assert client.delete(f"/wings/{wing['id']}", headers=_hdr(society)).status_code == 204
    assert client.get("/wings", headers=_hdr(society)).json() == []


# --- The agents must keep working (E6-S3 is where that changes) ------------

def test_adding_a_layout_does_not_disturb_existing_residents(society):
    """
    The layout is additive to the gate: the guard still types `A-101` and the
    agents still resolve it via residents.flat_number. E4-S4 adds the flat_id
    link alongside that string — it does not replace it (that's E6-S3).
    """
    with system_session() as db:
        db.add(m.Resident(society_id=society, flat_number="A-101", name="Priya Sharma"))
        db.flush()

    wing = _wing(society, name="A")
    client.post("/flats", headers=_hdr(society),
                json={"wing_id": wing["id"], "flat_number": "101", "floor": 1})

    with system_session() as db:
        r = db.execute(select(m.Resident).where(m.Resident.society_id == society)).scalars().one()
        assert r.flat_number == "A-101", "the string the agents resolve on is untouched"
        assert r.flat_id is not None, "E4-S4: the flat adopts the resident already on its code"
