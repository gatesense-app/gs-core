"""
Bulk resident CSV import — E3-S1 (upload) and E3-S2 (reject unsafe input).

The two things worth testing hard: the file is all-or-nothing (a bad row 250
leaves nothing behind), and it can't be weaponised (formula injection, an
oversize file, a `society_id` column trying to cross tenants). The happy path is
covered too, including the D3 case of several residents sharing one flat.

    python -m pytest backend/tests/test_import.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.main import app
from backend.security import create_access_token
from backend.tools import resolve

client = TestClient(app)

PLATFORM = {"Authorization": "Bearer " + create_access_token(
    user_id="00000000-0000-0000-0000-0000000000b1", society_id=None, role="platform_admin")}


def _hdr(society_id, role="society_admin"):
    return {"Authorization": "Bearer " + create_access_token(
        user_id="00000000-0000-0000-0000-0000000000b2",
        society_id=str(society_id), role=role)}


def _csv_headers(society_id, role="society_admin"):
    h = dict(_hdr(society_id, role))
    h["Content-Type"] = "text/csv"
    return h


@pytest.fixture(autouse=True)
def _cleanup():
    def purge():
        with system_session() as db:
            db.execute(text("DELETE FROM societies WHERE name LIKE 'IMP-Test%'"))
    purge()
    yield
    purge()


@pytest.fixture
def society():
    """A society with wings A and B declared, but no flats yet."""
    with system_session() as db:
        soc = m.Society(name="IMP-Test-Main")
        db.add(soc)
        db.flush()
        db.add(m.Wing(society_id=soc.id, name="A", floors=10, flats_per_floor=4))
        db.add(m.Wing(society_id=soc.id, name="B", floors=5, flats_per_floor=4))
        db.flush()
        return soc.id


def _post(society_id, body, *, dry_run=None, headers=None):
    url = "/import/residents"
    params = []
    if dry_run is not None:
        params.append(f"dry_run={'true' if dry_run else 'false'}")
    if params:
        url += "?" + "&".join(params)
    return client.post(url, headers=headers or _csv_headers(society_id), content=body)


class _Row:
    """Plain values: an ORM object detaches once its session closes."""

    def __init__(self, r):
        self.name = r.name
        self.phone = r.phone
        self.flat_number = r.flat_number
        self.flat_id = r.flat_id


def _residents(society_id):
    with system_session() as db:
        return [
            _Row(r) for r in db.execute(
                select(m.Resident).where(m.Resident.society_id == society_id)
            ).scalars().all()
        ]


HEADER = "wing,flat_number,floor,resident_name,phone,is_primary_contact\n"


# --- E3-S1: the happy path -------------------------------------------------

def test_preview_writes_nothing(society):
    body = HEADER + "A,101,1,Priya Sharma,+919812345678,yes\n"
    r = _post(society, body, dry_run=True)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["committed"] is False
    assert rep["residents_to_create"] == 1
    assert rep["flats_to_create"] == 1
    assert _residents(society) == []


def test_commit_creates_flats_and_residents(society):
    body = HEADER + "A,101,1,Priya Sharma,+919812345678,yes\n"
    r = _post(society, body, dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["committed"] is True

    with system_session() as db:
        flat = db.execute(select(m.Flat).where(
            m.Flat.society_id == society, m.Flat.code == "A-101")).scalars().one()
        assert flat.floor == 1
        res = db.execute(select(m.Resident).where(
            m.Resident.society_id == society, m.Resident.flat_number == "A-101")).scalars().one()
        assert res.name == "Priya Sharma"
        assert res.flat_id == flat.id  # linked, not just free text


def test_several_rows_share_a_flat_with_one_primary(society):
    """D3: three rows, wing A flat 101 -> one flat, three residents, one primary."""
    body = HEADER + (
        "A,101,1,Priya Sharma,+919812345678,\n"
        "A,101,1,Rohit Sharma,+919812345679,yes\n"
        "A,101,1,Anjali Sharma,,\n"
    )
    assert _post(society, body, dry_run=False).json()["committed"] is True

    with system_session() as db:
        flats = db.execute(select(m.Flat).where(m.Flat.society_id == society)).scalars().all()
        assert len(flats) == 1
    with scoped_session(society) as db:
        primary = resolve.primary_resident(db, society, "A-101")
        assert primary.name == "Rohit Sharma", "the row marked is_primary wins"
        assert len(resolve.flat_residents(db, society, "A-101")) == 3


def test_absent_a_mark_the_first_row_is_primary(society):
    body = HEADER + (
        "A,101,1,Priya Sharma,,\n"
        "A,101,1,Rohit Sharma,,\n"
    )
    _post(society, body, dry_run=False)
    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Priya Sharma"


def test_reimport_updates_rather_than_duplicates(society):
    """Natural key is (flat, name): the same person re-imported is updated."""
    _post(society, HEADER + "A,101,1,Priya Sharma,+919812345678,yes\n", dry_run=False)
    r = _post(society, HEADER + "A,101,1,Priya Sharma,+919899999999,yes\n", dry_run=False)
    assert r.json()["residents_to_update"] == 1
    assert r.json()["residents_to_create"] == 0

    res = _residents(society)
    assert len(res) == 1
    assert res[0].phone == "+919899999999"


# --- D4: a flat the import creates adopts who already lives there -----------

def _free_text_resident(society_id, flat_number, name, primary=True):
    """A resident from before there was a layout: real flat_number, no flat_id."""
    with system_session() as db:
        db.add(m.Resident(society_id=society_id, flat_number=flat_number,
                          name=name, is_primary=primary))
        db.flush()


def test_a_flat_the_import_creates_adopts_residents_already_on_its_code(society):
    """
    Parity with typing the flat in by hand: whichever path brings a flat into
    existence, it must not orphan the people already behind that door (D4).
    """
    _free_text_resident(society, "A-101", "Neha Sharma")
    _post(society, HEADER + "A,101,1,Ravi Kumar,+919812345000,\n", dry_run=False)

    with system_session() as db:
        neha = db.execute(select(m.Resident).where(
            m.Resident.society_id == society, m.Resident.name == "Neha Sharma")).scalars().one()
        flat = db.execute(select(m.Flat).where(
            m.Flat.society_id == society, m.Flat.code == "A-101")).scalars().one()
        assert neha.flat_id == flat.id, "the new flat adopted the resident already on A-101"


def test_the_preview_says_how_many_it_will_adopt(society):
    _free_text_resident(society, "A-101", "Neha Sharma")
    r = _post(society, HEADER + "A,101,1,Ravi Kumar,,\n", dry_run=True)
    body = r.json()
    assert body["residents_to_link"] == 1
    assert body["residents_to_create"] == 1   # Ravi; Neha is adopted, not created
    assert _residents(society)[0].flat_id is None, "a preview still writes nothing"


def test_a_resident_named_in_the_file_is_an_update_not_an_adoption(society):
    """Neha is in the file, so she's counted once — as an update, not adopted."""
    _free_text_resident(society, "A-101", "Neha Sharma")
    body = _post(society, HEADER + "A,101,1,Neha Sharma,,\n", dry_run=True).json()
    assert (body["residents_to_update"], body["residents_to_link"]) == (1, 0)


def test_importing_does_not_depose_an_adopted_residents_primary(society):
    """
    A file that says nothing about primaries must not quietly take the contact
    away from the household that already had one — adopting someone is not a
    reason to depose them.
    """
    _free_text_resident(society, "A-101", "Neha Sharma", primary=True)
    _post(society, HEADER + "A,101,1,Ravi Kumar,,\n", dry_run=False)

    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Neha Sharma"


def test_an_explicit_primary_row_does_take_over_from_an_adopted_resident(society):
    """...but saying so explicitly is exactly what is_primary_contact is for."""
    _free_text_resident(society, "A-101", "Neha Sharma", primary=True)
    _post(society, HEADER + "A,101,1,Ravi Kumar,,yes\n", dry_run=False)

    with scoped_session(society) as db:
        assert resolve.primary_resident(db, society, "A-101").name == "Ravi Kumar"
        assert len(resolve.flat_residents(db, society, "A-101")) == 2


def test_adoption_does_not_reach_an_unrelated_flat(society):
    _free_text_resident(society, "A-999", "Someone Else")
    _post(society, HEADER + "A,101,1,Ravi Kumar,,\n", dry_run=False)

    with system_session() as db:
        other = db.execute(select(m.Resident).where(
            m.Resident.society_id == society, m.Resident.name == "Someone Else")).scalars().one()
        assert other.flat_id is None


def test_platform_admin_must_name_a_society(society):
    body = HEADER + "A,101,1,Priya Sharma,,yes\n"
    h = dict(PLATFORM); h["Content-Type"] = "text/csv"
    assert client.post("/import/residents", headers=h, content=body).status_code == 422
    r = client.post(f"/import/residents?dry_run=false&society_id={society}", headers=h, content=body)
    assert r.status_code == 200 and r.json()["committed"] is True


def test_a_society_id_column_cannot_cross_tenants(society):
    """Tenancy never comes from the file: a society_id column is ignored."""
    with system_session() as db:
        other = m.Society(name="IMP-Test-Other")
        db.add(other)
        db.flush()
        other_id = other.id

    body = ("wing,flat_number,floor,resident_name,society_id\n"
            f"A,101,1,Priya Sharma,{other_id}\n")
    _post(society, body, dry_run=False)

    assert len(_residents(society)) == 1, "the resident lands in the caller's society"
    assert _residents(other_id) == []


def test_template_is_downloadable(society):
    r = client.get("/import/residents/template", headers=_hdr(society))
    assert r.status_code == 200
    assert r.text.startswith("wing,flat_number,floor,resident_name")
    assert "attachment" in r.headers.get("content-disposition", "")


# --- E3-S1: all-or-nothing -------------------------------------------------

def test_one_bad_row_rejects_the_whole_file(society):
    body = HEADER + (
        "A,101,1,Priya Sharma,,yes\n"
        "A,102,1,Arun Mehta,,\n"
        "Z,103,1,Ghost Person,,\n"       # unknown wing -> the whole file fails
    )
    r = _post(society, body, dry_run=False)
    assert r.status_code == 200
    assert r.json()["committed"] is False
    assert r.json()["rejected_rows"] == 1
    assert _residents(society) == [], "not one of the three valid-looking rows was written"


def test_errors_name_the_row_and_column(society):
    body = HEADER + "Z,101,notanumber,,\n"  # bad wing, bad floor, missing name
    r = _post(society, body, dry_run=True)
    errs = {(e["row"], e["column"]) for e in r.json()["errors"]}
    assert (2, "wing") in errs
    assert (2, "floor") in errs
    assert (2, "resident_name") in errs


def test_two_primaries_for_one_flat_is_an_error(society):
    body = HEADER + (
        "A,101,1,Priya Sharma,,yes\n"
        "A,101,1,Rohit Sharma,,yes\n"
    )
    r = _post(society, body, dry_run=True)
    assert r.json()["rejected_rows"] == 1
    assert any(e["column"] == "is_primary_contact" and "line 2" in e["message"]
               for e in r.json()["errors"])


def test_floor_conflicting_with_an_existing_flat_is_rejected(society):
    _post(society, HEADER + "A,101,1,Priya Sharma,,yes\n", dry_run=False)
    r = _post(society, HEADER + "A,101,5,Rohit Sharma,,\n", dry_run=True)
    assert r.json()["rejected_rows"] == 1
    assert any(e["column"] == "floor" for e in r.json()["errors"])


def test_floor_conflict_within_the_file_is_rejected(society):
    body = HEADER + (
        "A,101,1,Priya Sharma,,yes\n"
        "A,101,2,Rohit Sharma,,\n"      # same flat, different floor
    )
    r = _post(society, body, dry_run=True)
    assert r.json()["rejected_rows"] == 1
    assert any(e["column"] == "floor" for e in r.json()["errors"])


def test_unknown_wing_is_not_an_implicit_create(society):
    _post(society, HEADER + "C,101,1,Priya Sharma,,yes\n", dry_run=False)
    with system_session() as db:
        assert db.execute(select(func.count(m.Wing.id)).where(
            m.Wing.society_id == society)).scalar_one() == 2, "no phantom wing 'C'"


# --- E3-S2: unsafe / malformed --------------------------------------------

def test_empty_file_is_a_clear_error(society):
    r = _post(society, "", dry_run=True)
    assert r.status_code == 400
    assert "empty" in r.json()["error"]["message"].lower()


def test_missing_required_header_is_rejected(society):
    # no 'floor' column
    body = "wing,flat_number,resident_name\nA,101,Priya\n"
    r = _post(society, body, dry_run=True)
    assert r.status_code == 400
    assert "floor" in r.json()["error"]["message"]


def test_non_utf8_binary_is_rejected(society):
    r = client.post("/import/residents", headers=_csv_headers(society),
                    content=b"\xff\xfe\x00\x01\x02rubbish")
    assert r.status_code == 400
    assert "UTF-8" in r.json()["error"]["message"]


def test_oversize_file_is_refused(society):
    from backend import csv_import
    big = HEADER + ("A,101,1,X,," + "y" * 100 + "\n") * 1  # header row is fine
    # Forge a Content-Length past the cap without sending that many bytes.
    h = _csv_headers(society)
    h["Content-Length"] = str(csv_import.MAX_BYTES + 1)
    r = client.post("/import/residents", headers=h, content=big)
    assert r.status_code == 413


def test_formula_injection_in_a_name_is_neutralised(society):
    body = HEADER + "A,101,1,=SUM(1+1),,yes\n"
    assert _post(society, body, dry_run=False).json()["committed"] is True
    res = _residents(society)
    assert res[0].name == "'=SUM(1+1)", "a leading = is defanged with an apostrophe"


def test_injection_in_phone_is_a_validation_error_not_a_silent_store(society):
    body = HEADER + "A,101,1,Priya Sharma,=cmd|'/C calc',yes\n"
    r = _post(society, body, dry_run=True)
    assert r.json()["rejected_rows"] == 1
    assert any(e["column"] == "phone" for e in r.json()["errors"])


def test_whitespace_and_bom_are_tolerated(society):
    # UTF-8 BOM, padded cells; A-101 with trailing space must equal A-101.
    body = "﻿" + HEADER + "  A , 101 , 1 , Priya Sharma , +919812345678 , yes \n"
    r = _post(society, body, dry_run=False)
    assert r.status_code == 200 and r.json()["committed"] is True
    res = _residents(society)
    assert res[0].name == "Priya Sharma"
    assert res[0].flat_number == "A-101"


# --- Roles -----------------------------------------------------------------

def test_guards_and_residents_cannot_import(society):
    body = HEADER + "A,101,1,Priya Sharma,,yes\n"
    for role in ("guard", "resident"):
        r = _post(society, body, dry_run=True, headers=_csv_headers(society, role))
        assert r.status_code == 403, role
    assert client.get("/import/residents/template",
                      headers=_hdr(society, "guard")).status_code == 403
