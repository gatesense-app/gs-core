"""
Society layout — wings (E4-S1) and flats (E4-S2).

The split follows D2: a wing *declares the shape of a grid* and creates no
flats; a flat is entered one at a time with a code the admin typed. Nothing here
generates or infers a code, and nothing derives a floor from one (Q1).

Editing a wing (E4-S3), reconcile (E4-S4) and CSV import (E3) are later stories.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid, resolve_society_id
from backend.schemas import FlatCreate, FlatResponse, WingCreate, WingResponse

router = APIRouter(tags=["layout"])

_admins = require_role("platform_admin", "society_admin")


def _flat_counts(db, wing_ids: list) -> dict:
    """wing_id -> number of actual flats. One query, not N."""
    if not wing_ids:
        return {}
    rows = db.execute(
        select(m.Flat.wing_id, func.count(m.Flat.id))
        .where(m.Flat.wing_id.in_(wing_ids))
        .group_by(m.Flat.wing_id)
    ).all()
    return {wid: count for wid, count in rows}


def _wing_resp(w: m.Wing, flat_count: int) -> WingResponse:
    return WingResponse(
        id=str(w.id),
        society_id=str(w.society_id),
        name=w.name,
        floors=w.floors,
        flats_per_floor=w.flats_per_floor,
        flat_count=flat_count,
    )


def _flat_resp(f: m.Flat, wing_name: str, warnings: list[str] | None = None) -> FlatResponse:
    return FlatResponse(
        id=str(f.id),
        society_id=str(f.society_id),
        wing_id=str(f.wing_id),
        wing_name=wing_name,
        flat_number=f.flat_number,
        floor=f.floor,
        code=f.code,
        warnings=warnings or [],
    )


def _get_wing(db, wing_id: str) -> m.Wing:
    wing = db.get(m.Wing, parse_uuid(wing_id))
    if wing is None:  # RLS hides other societies' rows -> looks like 404
        raise HTTPException(404, "Wing not found")
    return wing


# ---------------------------------------------------------------------------
# E4-S1 — wings
# ---------------------------------------------------------------------------
@router.post("/wings", status_code=201, response_model=WingResponse)
def create_wing(body: WingCreate, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Declare a wing. Creates no flats — the grid renders empty until they are
    entered (E4-S2) or imported (E3). Floors/flats-per-floor may differ freely
    between wings in the same society.
    """
    society_id = resolve_society_id(user, body.society_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Wing name is required")

    # Checked up front for a clear message; the unique constraint is the real guard.
    exists = db.execute(
        select(m.Wing.id).where(m.Wing.society_id == society_id, m.Wing.name == name)
    ).first()
    if exists:
        raise HTTPException(409, f"A wing named '{name}' already exists in this society")

    wing = m.Wing(
        society_id=society_id,
        name=name,
        floors=body.floors,
        flats_per_floor=body.flats_per_floor,
    )
    db.add(wing)
    try:
        db.flush()
    except Exception:
        # Lost a race against a concurrent create with the same name.
        raise HTTPException(409, f"A wing named '{name}' already exists in this society")
    return _wing_resp(wing, 0)


@router.get("/wings", response_model=list[WingResponse])
def list_wings(
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """A society's wings, each with its real flat count."""
    sid = resolve_society_id(user, society_id)
    rows = db.execute(
        select(m.Wing).where(m.Wing.society_id == parse_uuid(sid)).order_by(m.Wing.name)
    ).scalars().all()
    counts = _flat_counts(db, [w.id for w in rows])
    return [_wing_resp(w, counts.get(w.id, 0)) for w in rows]


@router.get("/wings/{wing_id}", response_model=WingResponse)
def get_wing(wing_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    wing = _get_wing(db, wing_id)
    return _wing_resp(wing, _flat_counts(db, [wing.id]).get(wing.id, 0))


@router.delete("/wings/{wing_id}", status_code=204)
def delete_wing(wing_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Remove a wing declared by mistake. Refused once it has flats — the CASCADE
    would take occupied flats with it, which is not a thing to do silently.
    """
    wing = _get_wing(db, wing_id)
    count = _flat_counts(db, [wing.id]).get(wing.id, 0)
    if count:
        raise HTTPException(
            409,
            f"Wing '{wing.name}' still has {count} flat(s). Delete them first.",
        )
    db.delete(wing)
    db.flush()


# ---------------------------------------------------------------------------
# E4-S2 — flats
# ---------------------------------------------------------------------------
def _shape_warnings(db, wing: m.Wing, floor: int) -> list[str]:
    """
    Q2: the declared shape is a hint, never a rule. Ground-floor shops and
    penthouses are normal, so we say something and save anyway.
    """
    warnings = []
    if floor > wing.floors:
        warnings.append(
            f"Floor {floor} is above the {wing.floors} floor(s) declared for wing "
            f"'{wing.name}'. Saved anyway."
        )
    on_floor = db.execute(
        select(func.count(m.Flat.id)).where(m.Flat.wing_id == wing.id, m.Flat.floor == floor)
    ).scalar_one()
    if on_floor >= wing.flats_per_floor:
        warnings.append(
            f"Floor {floor} now has {on_floor + 1} flats; wing '{wing.name}' declares "
            f"{wing.flats_per_floor} per floor. Saved anyway."
        )
    return warnings


@router.post("/flats", status_code=201, response_model=FlatResponse)
def create_flat(body: FlatCreate, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Add a flat to a wing: `code = "{wing}-{flat_number}"` from the number the
    admin typed. The society comes from the wing, not the body — the wing was
    already resolved through RLS, so it can't point outside the caller's tenant.
    """
    wing = _get_wing(db, body.wing_id)
    flat_number = body.flat_number.strip()
    if not flat_number:
        raise HTTPException(422, "Flat number is required")
    code = f"{wing.name}-{flat_number}"

    exists = db.execute(
        select(m.Flat.id).where(m.Flat.society_id == wing.society_id, m.Flat.code == code)
    ).first()
    if exists:
        raise HTTPException(409, f"Flat '{code}' already exists in this society")

    # Read the floor's occupancy before inserting, so the count is of the others.
    warnings = _shape_warnings(db, wing, body.floor)

    flat = m.Flat(
        society_id=wing.society_id,
        wing_id=wing.id,
        flat_number=flat_number,
        floor=body.floor,
        code=code,
    )
    db.add(flat)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, f"Flat '{code}' already exists in this society")
    return _flat_resp(flat, wing.name, warnings)


@router.get("/flats", response_model=list[FlatResponse])
def list_flats(
    wing_id: str | None = None,
    society_id: str | None = None,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """This society's flats, newest floor-first order; optionally one wing's."""
    sid = resolve_society_id(user, society_id)
    q = (
        select(m.Flat, m.Wing.name)
        .join(m.Wing, m.Flat.wing_id == m.Wing.id)
        .where(m.Flat.society_id == parse_uuid(sid))
        .order_by(m.Wing.name, m.Flat.floor, m.Flat.flat_number)
    )
    if wing_id:
        q = q.where(m.Flat.wing_id == parse_uuid(wing_id))
    return [_flat_resp(f, wing_name) for f, wing_name in db.execute(q).all()]


@router.get("/flats/{flat_id}", response_model=FlatResponse)
def get_flat(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None:
        raise HTTPException(404, "Flat not found")
    return _flat_resp(flat, db.get(m.Wing, flat.wing_id).name)


@router.delete("/flats/{flat_id}", status_code=204)
def delete_flat(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    Refused when the flat has residents or visitor history — silently removing
    an occupied flat, or orphaning the history a guard logged against it, is
    unacceptable (E4-S3).
    """
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None:
        raise HTTPException(404, "Flat not found")

    residents = db.execute(
        select(func.count(m.Resident.id)).where(m.Resident.flat_id == flat.id)
    ).scalar_one()
    if residents:
        raise HTTPException(409, f"Flat '{flat.code}' still has {residents} resident(s)")

    # History is free text (the agents still resolve by typed string until E6-S3),
    # so this matches on the code rather than an FK.
    history = db.execute(
        select(func.count(m.VisitorSession.id)).where(
            m.VisitorSession.society_id == flat.society_id,
            m.VisitorSession.flat_number == flat.code,
        )
    ).scalar_one()
    if history:
        raise HTTPException(409, f"Flat '{flat.code}' has visitor history and cannot be deleted")

    db.delete(flat)
    db.flush()
