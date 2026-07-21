"""
Bulk resident import from CSV (E3).

Kept apart from the router so the rules that matter — what's valid, what's a
formula, what counts as "the same resident" — are testable without HTTP.

The flow is preview-then-commit. `build_report` parses and validates against the
live layout and returns exactly what a commit *would* do: how many residents get
created vs updated, which flats get made, and every rejected row with its line
number and offending column. A commit runs the identical validation and only
writes when nothing is rejected — the file is all-or-nothing, so row 250 being
bad never leaves 249 half-imported residents (that atomicity is the caller's
single transaction; this module just refuses to apply a plan with errors).

Columns (D2 states the parts of the code; the system never invents them):

    wing, flat_number, floor, resident_name, phone, is_primary_contact

`code = "{wing}-{flat_number}"`. Several rows may share a flat (D3): three rows
for wing A / flat 101 make one flat with three residents. `is_primary_contact`
marks the one the intercom agent reaches; absent it, the first row for that flat
wins (Q3). Two rows both claiming primary for one flat is an error, not a
coin-flip.

Natural key for "update, don't duplicate": (society_id, code, name),
case-insensitive on name. Flat alone can't be the key once a flat holds several
people (D3); the name is what tells them apart.
"""

import csv
import io
import os

from sqlalchemy import select

from backend import audit
from backend import db_models as m
from backend.tools import resolve

# A 2M-row file must not take the API down. The router enforces the byte cap
# while reading the body; the row cap is a second ceiling for a small-but-dense
# file. Both are generous for a real society (500 flats, a few residents each).
MAX_BYTES = int(os.getenv("IMPORT_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MiB
MAX_ROWS = int(os.getenv("IMPORT_MAX_ROWS", "20000"))

REQUIRED_COLUMNS = ["wing", "flat_number", "floor", "resident_name"]
OPTIONAL_COLUMNS = ["phone", "is_primary_contact"]
TEMPLATE = (
    "wing,flat_number,floor,resident_name,phone,is_primary_contact\n"
    "A,101,1,Priya Sharma,+919812345678,yes\n"
    "A,101,1,Rohit Sharma,+919812345679,no\n"
    "B,201,2,Arun Mehta,+919812345680,\n"
)

# Leading characters a spreadsheet interprets as a formula. A cell starting with
# one is neutralised (prefixed with ') so a later export can't execute it.
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_TRUE = {"yes", "true", "1", "y", "primary"}
_FALSE = {"no", "false", "0", "n", ""}


class ImportError_(Exception):
    """A structural problem that stops parsing before any row is looked at."""


def neutralize(value: str) -> str:
    """
    Defang a cell that a spreadsheet would treat as a formula.

    OWASP CSV-injection guidance: a value beginning =, +, -, or @ becomes a live
    formula on open/export. Prefixing an apostrophe forces it to stay text.
    Applied to free text we store (names); structured fields (phone, floor,
    is_primary) are validated by shape instead, so an injected phone is a row
    error rather than a silently rewritten value.
    """
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _parse_bool(raw: str):
    """Tri-state: True / False / None (unset). Anything else is invalid."""
    v = raw.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return "invalid"


def parse(text: str) -> list[dict]:
    """
    CSV text -> a list of raw row dicts tagged with their file line number.

    Handles a UTF-8 BOM and trims every cell. Raises ImportError_ for the
    structural failures E3-S2 calls out: empty file, missing header, a header
    without the required columns. A `society_id` column is dropped here so
    nothing downstream can read it (tenancy never comes from the file).
    """
    if text.startswith("﻿"):
        text = text[1:]
    if not text.strip():
        raise ImportError_("The file is empty.")

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise ImportError_("The file is empty.")

    cols = [h.strip().lower() for h in header]
    missing = [c for c in REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise ImportError_(
            "Missing required column(s): " + ", ".join(missing)
            + f". Expected header: {','.join(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)}"
        )

    known = set(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
    rows = []
    # enumerate from 2: the header is line 1, so the first data row is line 2 —
    # the number the admin sees in their editor/spreadsheet.
    for line_no, raw in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw):
            continue  # skip fully blank lines rather than erroring on them
        record = {"_line": line_no}
        for i, col in enumerate(cols):
            if col in known:
                record[col] = raw[i].strip() if i < len(raw) else ""
        rows.append(record)
        if len(rows) > MAX_ROWS:
            raise ImportError_(f"Too many rows (limit {MAX_ROWS}).")

    return rows


def _err(errors, line, column, message):
    errors.append({"row": line, "column": column, "message": message})


def validate(db, society_id, rows: list[dict]) -> dict:
    """
    Check every row against the live layout and each other; return a plan plus
    the full list of rejections (row number + column + why).

    Nothing is written. The caller commits the plan only when `errors` is empty.
    """
    errors: list[dict] = []

    # Wings this society actually has — an unknown wing is an error, never an
    # implicit create, so a typo ("a" vs "A") can't spawn a phantom wing.
    wings = {
        w.name: w
        for w in db.execute(
            select(m.Wing).where(m.Wing.society_id == society_id)
        ).scalars().all()
    }

    existing_flats = {
        f.code: f
        for f in db.execute(
            select(m.Flat).where(
                m.Flat.society_id == society_id, m.Flat.deleted_at.is_(None))
        ).scalars().all()
    }

    # Per-flat accumulation across the file: the floor everyone agrees on, and
    # who (if anyone) is marked primary.
    flat_floor: dict[str, int] = {}
    flat_primary_line: dict[str, int] = {}
    valid_rows: list[dict] = []

    for r in rows:
        line = r["_line"]
        wing_name = r.get("wing", "")
        flat_number = r.get("flat_number", "")
        floor_raw = r.get("floor", "")
        name = r.get("resident_name", "")

        row_ok = True
        if not wing_name:
            _err(errors, line, "wing", "Wing is required."); row_ok = False
        elif wing_name not in wings:
            _err(errors, line, "wing", f"Unknown wing '{wing_name}'. Create it first."); row_ok = False
        if not flat_number:
            _err(errors, line, "flat_number", "Flat number is required."); row_ok = False
        if not name:
            _err(errors, line, "resident_name", "Resident name is required."); row_ok = False

        floor = None
        if not floor_raw:
            _err(errors, line, "floor", "Floor is required."); row_ok = False
        else:
            try:
                floor = int(floor_raw)
            except ValueError:
                _err(errors, line, "floor", f"Floor must be a whole number, got '{floor_raw}'."); row_ok = False

        primary = None
        raw_primary = r.get("is_primary_contact", "")
        parsed_primary = _parse_bool(raw_primary)
        if parsed_primary == "invalid":
            _err(errors, line, "is_primary_contact",
                 f"Expected yes/no, got '{raw_primary}'."); row_ok = False
        else:
            primary = parsed_primary

        phone = r.get("phone", "")
        if phone and not _looks_like_phone(phone):
            _err(errors, line, "phone", f"'{phone}' is not a valid phone number."); row_ok = False

        if not row_ok:
            continue

        code = f"{wing_name}-{flat_number}"

        # Floor must be consistent: with the existing flat, and with the other
        # rows in this file for the same flat. A contradiction is an error, not
        # a silent overwrite.
        prior = existing_flats.get(code)
        if prior is not None and prior.floor != floor:
            _err(errors, line, "floor",
                 f"Flat '{code}' is on floor {prior.floor}; this row says {floor}.")
            continue
        if code in flat_floor and flat_floor[code] != floor:
            _err(errors, line, "floor",
                 f"Flat '{code}' was floor {flat_floor[code]} on an earlier row; this row says {floor}.")
            continue
        flat_floor[code] = floor

        if primary is True:
            if code in flat_primary_line:
                _err(errors, line, "is_primary_contact",
                     f"Flat '{code}' already has a primary on line {flat_primary_line[code]}.")
                continue
            flat_primary_line[code] = line

        valid_rows.append({
            "line": line, "code": code, "wing_name": wing_name,
            "flat_number": flat_number, "floor": floor,
            "name": name, "phone": phone, "primary": primary,
        })

    # Match rows to existing residents by the natural key (code, lower(name)).
    existing_residents = _resident_index(db, society_id)
    to_create = to_update = 0
    file_keys = set()
    for vr in valid_rows:
        key = (vr["code"], vr["name"].lower())
        file_keys.add(key)
        if key in existing_residents:
            to_update += 1
        else:
            to_create += 1

    flats_to_create = sorted(c for c in flat_floor if c not in existing_flats)

    # Residents the new flats will adopt (D4): already on the code, not yet
    # linked, and not named in the file — the ones in the file are counted above
    # as created/updated. Predicted here so the preview can say it out loud;
    # silently swallowing a household would be the same bug as a silent rename.
    new_codes = set(flats_to_create)
    to_link = sum(
        1
        for (code, name), r in existing_residents.items()
        if code in new_codes and r.flat_id is None and (code, name) not in file_keys
    )

    return {
        "errors": errors,
        "plan": {
            "rows": valid_rows,
            "flats_to_create": flats_to_create,
            "flat_floor": flat_floor,
            "flat_primary_line": flat_primary_line,
            "wings": wings,
            "existing_flats": existing_flats,
            "existing_residents": existing_residents,
        },
        "counts": {
            "total_rows": len(rows),
            "residents_to_create": to_create,
            "residents_to_update": to_update,
            "residents_to_link": to_link,
            "flats_to_create": len(flats_to_create),
            "rejected_rows": len({e["row"] for e in errors}),
        },
    }


def apply_plan(db, society_id, plan: dict, user=None) -> None:
    """
    Write a validated plan in the caller's transaction (E3-S1).

    Assumes `validate` returned no errors — a plan with rejected rows is never
    applied. Creates missing flats, upserts residents by natural key, then
    settles exactly one primary per touched flat. Each change is recorded on the
    timeline (audit) so an import reads there exactly like the same edits done by
    hand — the path that created a flat or a resident is not something anyone
    should be able to feel afterwards.
    """
    wings = plan["wings"]
    flats = dict(plan["existing_flats"])

    # 1. Flats the file introduces (D2 note 3: import is the bulk create path).
    #    Each one adopts the free-text residents already sitting on its code,
    #    exactly as typing the flat in by hand does (D4) — a flat coming into
    #    existence must not orphan the people already behind that door, and which
    #    path created it is not a distinction anyone should be able to feel.
    for code in plan["flats_to_create"]:
        wing = _wing_for(wings, code)
        flat = m.Flat(
            society_id=society_id, wing_id=wing.id,
            flat_number=code[len(wing.name) + 1:], floor=plan["flat_floor"][code],
            code=code,
        )
        db.add(flat)
        db.flush()
        flats[code] = flat
        linked = resolve.link_exact_matches(db, society_id, flat)
        summary = f"Flat {code} added on floor {flat.floor} (imported)"
        if linked:
            summary += f", adopting {linked} existing resident(s)"
        audit.record(
            db, society_id=society_id, user=user, action="flat_created",
            summary=summary, entity_type=audit.FLAT, entity_id=flat.id,
            flat_id=flat.id, flat_code=code,
            detail={"floor": flat.floor, "linked_residents": linked, "via": "import"},
        )

    # 2. Residents: update the ones we already have, create the rest, and link
    #    each to its flat so the layout and the agents agree. Keep each row's
    #    resident so step 3 can promote the right one without re-matching a name
    #    we may have neutralised on the way in.
    existing = plan["existing_residents"]
    # Imported residents are the flat's owners/household — CSV import has no
    # tenancy concept, so role defaults to owner. Tenants come only through a
    # tenancy (routers/tenancies.py).
    resident_by_line: dict[int, m.Resident] = {}
    for vr in plan["rows"]:
        flat = flats[vr["code"]]
        key = (vr["code"], vr["name"].lower())
        resident = existing.get(key)
        is_new = resident is None
        if is_new:
            resident = m.Resident(
                society_id=society_id, flat_number=vr["code"], name=neutralize(vr["name"]),
            )
            db.add(resident)
        resident.flat_id = flat.id
        resident.flat_number = vr["code"]
        if vr["phone"]:
            resident.phone = vr["phone"]
        db.flush()
        resident_by_line[vr["line"]] = resident
        audit.record(
            db, society_id=society_id, user=user,
            action="resident_added" if is_new else "resident_edited",
            summary=f"{resident.name} {'added to' if is_new else 'updated on'} "
                    f"{vr['code']} (imported)",
            entity_type=audit.RESIDENT, entity_id=resident.id,
            flat_id=flat.id, flat_code=vr["code"],
        )

    # The first row for each flat, in file order — Q3's tiebreak when no row is
    # marked. It has to be explicit: rows imported in one transaction share a
    # created_at, and gen_random_uuid() isn't monotonic, so ensure_primary's
    # (created_at, id) order would pick an arbitrary row.
    first_line = {}
    for vr in plan["rows"]:
        first_line.setdefault(vr["code"], vr["line"])

    # 3. One primary per touched flat, deterministically (E6-S3 / Q3).
    for code in plan["flat_floor"]:
        line = plan["flat_primary_line"].get(code)
        if line is None and not resolve.has_primary(db, society_id, code):
            # Nobody is the contact for this door yet, so the first row wins (Q3).
            # Gated on has_primary rather than "is this flat new": a new flat can
            # arrive with an adopted resident who already holds the flag, and a
            # file that said nothing about primaries must not depose them. Saying
            # so is what is_primary_contact is for.
            line = first_line.get(code)
        if line is not None:
            resolve.claim_primary(db, resident_by_line[line])
        else:
            resolve.ensure_primary(db, society_id, code)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _wing_for(wings: dict, code: str):
    """The wing whose name is the code's prefix. Wing names may contain '-'."""
    for name, wing in wings.items():
        if code == name or code.startswith(name + "-"):
            return wing
    raise KeyError(code)  # unreachable: validation rejected unknown wings


def _resident_index(db, society_id) -> dict:
    """
    (code, lower(name)) -> live Resident, for natural-key upsert.

    Soft-deleted residents are excluded: re-importing a removed person creates a
    fresh resident rather than resurrecting a deleted one — restore is a separate,
    deliberate action, not a side effect of an import (there is no restore yet).
    """
    rows = db.execute(
        select(m.Resident).where(
            m.Resident.society_id == society_id, m.Resident.deleted_at.is_(None))
    ).scalars().all()
    return {(r.flat_number, r.name.lower()): r for r in rows}


def _looks_like_phone(value: str) -> bool:
    """
    A phone is digits with optional +, spaces, hyphens. Deliberately strict
    enough that a formula (=, @, or a bare word) fails here rather than being
    stored — structured fields are validated by shape, not neutralised.
    """
    stripped = value.replace(" ", "").replace("-", "")
    if stripped.startswith("+"):
        stripped = stripped[1:]
    return stripped.isdigit() and 6 <= len(stripped) <= 15
