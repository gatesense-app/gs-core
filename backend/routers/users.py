from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend import audit
from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import mask_phone, normalize_phone, parse_uuid, resolve_society_id, society_hides_phone
from backend.schemas import (
    ProvisionedRow,
    ProvisionRequest,
    ProvisionResult,
    SkippedRow,
    UserCreate,
    UserResponse,
)
from backend.security import hash_password
from backend.tools import resolve

router = APIRouter(prefix="/users", tags=["users"])

_admins = require_role("platform_admin", "society_admin")


def _to_resp(db, u: m.User) -> UserResponse:
    # A resident login's identifier is a phone; mask it for staff when the
    # society opts in (the resident already knows their own number).
    phone = u.phone
    if phone and society_hides_phone(db, u.society_id):
        phone = mask_phone(phone)
    return UserResponse(
        id=str(u.id),
        email=u.email,
        phone=phone,
        role=u.role,
        full_name=u.full_name,
        society_id=str(u.society_id) if u.society_id else None,
        is_active=u.is_active,
    )


@router.get("", response_model=list[UserResponse])
def list_users(_: CurrentUser = Depends(_admins), db=Depends(get_db)):
    rows = db.execute(select(m.User).order_by(m.User.email)).scalars().all()
    return [_to_resp(db, u) for u in rows]


@router.post("", status_code=201, response_model=UserResponse)
def create_user(body: UserCreate, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    society_id = resolve_society_id(user, body.society_id)
    new_user = m.User(
        society_id=society_id,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role=body.role,
        full_name=body.full_name,
        resident_id=parse_uuid(body.resident_id) if body.resident_id else None,
    )
    db.add(new_user)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, "A user with that email already exists")
    return _to_resp(db, new_user)


@router.post("/provision-residents", response_model=ProvisionResult)
def provision_residents(
    body: ProvisionRequest,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Give portal logins to a building's residents in one pass.

    For every live resident that doesn't already have a login, create a
    `resident` user they sign in with by **phone** and the supplied shared
    password. Idempotent — residents already linked (or without a usable phone)
    are skipped with a reason, so re-running only provisions the newcomers.
    """
    society_id = parse_uuid(resolve_society_id(user, body.society_id))
    pw_hash = hash_password(body.default_password)

    residents = db.execute(
        select(m.Resident)
        .where(m.Resident.society_id == society_id, m.Resident.deleted_at.is_(None))
        .order_by(m.Resident.flat_number, m.Resident.id)
    ).scalars().all()

    if body.wing_id:
        codes = set(db.execute(
            select(m.Flat.code).where(
                m.Flat.wing_id == parse_uuid(body.wing_id),
                m.Flat.deleted_at.is_(None))
        ).scalars().all())
        residents = [r for r in residents if r.flat_number in codes]

    # Everything a new login must not collide with, read once.
    linked = set(db.execute(
        select(m.User.resident_id).where(m.User.resident_id.is_not(None))
    ).scalars().all())
    taken_phones = set(db.execute(
        select(m.User.phone).where(m.User.phone.is_not(None))
    ).scalars().all())

    hide = society_hides_phone(db, society_id)
    created: list[ProvisionedRow] = []
    skipped: list[SkippedRow] = []
    for r in residents:
        if r.id in linked:
            skipped.append(SkippedRow(name=r.name, flat_number=r.flat_number,
                                      reason="already has a login"))
            continue
        phone = normalize_phone(r.phone)
        if not phone:
            skipped.append(SkippedRow(name=r.name, flat_number=r.flat_number,
                                      reason="no phone on record"))
            continue
        if phone in taken_phones:
            skipped.append(SkippedRow(name=r.name, flat_number=r.flat_number,
                                      reason="phone already used by another login"))
            continue

        # The phone unique index is global (a number is one login platform-wide),
        # but taken_phones only sees this society under RLS — a collision with
        # another society surfaces here. A savepoint lets us skip it cleanly
        # instead of failing the whole request.
        new = m.User(
            society_id=society_id, email=None, phone=phone, password_hash=pw_hash,
            role="resident", full_name=r.name, resident_id=r.id,
        )
        try:
            with db.begin_nested():
                db.add(new)
                db.flush()
        except IntegrityError:
            skipped.append(SkippedRow(name=r.name, flat_number=r.flat_number,
                                      reason="phone already used by another login"))
            continue
        taken_phones.add(phone)
        linked.add(r.id)
        audit.record(
            db, society_id=society_id, user=user, action="resident_login_provisioned",
            summary=f"Portal login provisioned for {r.name}",  # no number on the timeline
            entity_type=audit.RESIDENT, entity_id=r.id,
            flat_id=(f.id if (f := resolve.flat_for(db, society_id, r.flat_number)) else None),
            flat_code=r.flat_number,
        )
        created.append(ProvisionedRow(
            resident_id=str(r.id), name=r.name, flat_number=r.flat_number,
            phone=mask_phone(phone) if hide else phone))

    return ProvisionResult(
        created_count=len(created), skipped_count=len(skipped),
        created=created, skipped=skipped,
    )
