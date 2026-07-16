from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from backend import db_models as m
from backend.deps import get_db, require_role
from backend.routers.common import parse_uuid
from backend.schemas import SocietyCreate, SocietyResponse, SocietyUpdate
from backend.security import hash_password

router = APIRouter(prefix="/societies", tags=["societies"])


def _admin_counts(db, society_ids: list) -> dict:
    """society_id -> number of society_admins. One query, not N."""
    if not society_ids:
        return {}
    rows = db.execute(
        select(m.User.society_id, func.count(m.User.id))
        .where(m.User.role == "society_admin", m.User.society_id.in_(society_ids))
        .group_by(m.User.society_id)
    ).all()
    return {sid: count for sid, count in rows}


def _flat_counts(db, society_ids: list) -> dict:
    """
    society_id -> number of actual flats (E4-S1).

    Counted from the flats that exist, never floors * flats_per_floor: the
    declared shape is a hint (Q2), so deriving the total would let it lie.
    """
    if not society_ids:
        return {}
    rows = db.execute(
        select(m.Flat.society_id, func.count(m.Flat.id))
        .where(m.Flat.society_id.in_(society_ids))
        .group_by(m.Flat.society_id)
    ).all()
    return {sid: count for sid, count in rows}


@router.post("", status_code=201, response_model=SocietyResponse)
def create_society(
    body: SocietyCreate,
    _=Depends(require_role("platform_admin")),
    db=Depends(get_db),
):
    """
    Create a society, optionally with its first admin.

    The admin is optional so a property can be onboarded before it's known who
    will run it; one can be allocated at any time afterwards via
    POST /users (role=society_admin, society_id=<this society>).
    """
    society = m.Society(name=body.name, address=body.address)
    db.add(society)
    db.flush()  # populates society.id (RETURNING)

    admin_count = 0
    if body.admin_email:  # schema guarantees the password came with it
        db.add(
            m.User(
                society_id=society.id,
                email=body.admin_email.lower(),
                password_hash=hash_password(body.admin_password),
                role="society_admin",
                full_name=body.admin_name,
            )
        )
        try:
            db.flush()
        except Exception:
            # Otherwise the society is created and the admin silently isn't.
            raise HTTPException(409, "A user with that email already exists")
        admin_count = 1

    return SocietyResponse(
        id=str(society.id),
        name=society.name,
        address=society.address,
        created_at=society.created_at,
        admin_count=admin_count,
        flat_count=0,  # a new society has no layout yet
    )


@router.get("", response_model=list[SocietyResponse])
def list_societies(
    _=Depends(require_role("platform_admin", "society_admin")),
    db=Depends(get_db),
):
    rows = db.execute(select(m.Society).order_by(m.Society.created_at)).scalars().all()
    ids = [s.id for s in rows]
    counts = _admin_counts(db, ids)
    flats = _flat_counts(db, ids)
    return [
        SocietyResponse(
            id=str(s.id),
            name=s.name,
            address=s.address,
            created_at=s.created_at,
            admin_count=counts.get(s.id, 0),
            flat_count=flats.get(s.id, 0),
        )
        for s in rows
    ]


@router.patch("/{society_id}", response_model=SocietyResponse)
def update_society(
    society_id: str,
    body: SocietyUpdate,
    _=Depends(require_role("platform_admin")),
    db=Depends(get_db),
):
    """
    Edit a society's own details (name, address).

    Platform admin only: a society renaming itself is a different decision, and
    not one this story took. Touches nothing but the society row — residents,
    users and sessions are unaffected.
    """
    society = db.get(m.Society, parse_uuid(society_id))
    if society is None:  # RLS hides other tenants -> looks like 404
        raise HTTPException(404, "Society not found")

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Nothing to update")
    for key, value in fields.items():
        setattr(society, key, value)
    db.flush()

    counts = _admin_counts(db, [society.id])
    flats = _flat_counts(db, [society.id])
    return SocietyResponse(
        id=str(society.id),
        name=society.name,
        address=society.address,
        created_at=society.created_at,
        admin_count=counts.get(society.id, 0),
        flat_count=flats.get(society.id, 0),
    )
