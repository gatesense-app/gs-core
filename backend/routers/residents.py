from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid, resolve_society_id
from backend.schemas import ResidentCreate, ResidentResponse, ResidentUpdate
from backend.tools import resolve

router = APIRouter(prefix="/residents", tags=["residents"])

_admins = require_role("platform_admin", "society_admin")


def _to_resp(r: m.Resident) -> ResidentResponse:
    return ResidentResponse(
        id=str(r.id),
        society_id=str(r.society_id),
        flat_number=r.flat_number,
        name=r.name,
        phone=r.phone,
        is_primary=r.is_primary,
        standing_rules=r.standing_rules or [],
        delivery_preferences=r.delivery_preferences or {},
    )


@router.get("", response_model=list[ResidentResponse])
def list_residents(_: CurrentUser = Depends(_admins), db=Depends(get_db)):
    rows = db.execute(select(m.Resident).order_by(m.Resident.flat_number)).scalars().all()
    return [_to_resp(r) for r in rows]


@router.post("", status_code=201, response_model=ResidentResponse)
def create_resident(body: ResidentCreate, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    society_id = resolve_society_id(user, body.society_id)
    resident = m.Resident(
        society_id=society_id,
        flat_number=body.flat_number,
        name=body.name,
        phone=body.phone,
        standing_rules=body.standing_rules,
        delivery_preferences=body.delivery_preferences,
    )
    db.add(resident)
    db.flush()
    # Q3: the first resident added for a flat is its contact. A later one joins
    # the household without stealing the slot.
    resolve.ensure_primary(db, society_id, resident.flat_number)
    return _to_resp(resident)


@router.get("/{resident_id}", response_model=ResidentResponse)
def get_resident(resident_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    resident = db.get(m.Resident, parse_uuid(resident_id))
    if resident is None:  # RLS hides other societies' rows -> looks like 404
        raise HTTPException(404, "Resident not found")
    return _to_resp(resident)


@router.patch("/{resident_id}", response_model=ResidentResponse)
def update_resident(
    resident_id: str,
    body: ResidentUpdate,
    _: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    resident = db.get(m.Resident, parse_uuid(resident_id))
    if resident is None:
        raise HTTPException(404, "Resident not found")

    fields = body.model_dump(exclude_unset=True)
    want_primary = fields.pop("is_primary", None)
    if want_primary is False:
        # A flat always needs a contact, so "stop being primary" is not an
        # instruction we can honour on its own — promote someone else instead.
        raise HTTPException(
            422,
            "Promote another resident of this flat instead of demoting this one",
        )

    old_flat_number = resident.flat_number
    moving = "flat_number" in fields and fields["flat_number"] != old_flat_number
    if moving:
        # The primary slot is per flat: carrying the flag onto the new door
        # would collide with whoever holds it there.
        resolve.release_primary(db, resident)

    for key, value in fields.items():
        setattr(resident, key, value)
    db.flush()

    if moving:
        # Neither door is left uncontactable.
        resolve.ensure_primary(db, resident.society_id, old_flat_number)
        resolve.ensure_primary(db, resident.society_id, resident.flat_number)
    if want_primary:
        resolve.claim_primary(db, resident)
    return _to_resp(resident)


@router.delete("/{resident_id}", status_code=204)
def delete_resident(resident_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    resident = db.get(m.Resident, parse_uuid(resident_id))
    if resident is None:  # RLS hides other societies' rows -> looks like 404
        raise HTTPException(404, "Resident not found")

    # Capture before the delete: the ORM object is expired afterwards, and we
    # need these to re-settle the door. Removing the last resident leaves the
    # flat vacant — the flats row is untouched, only the resident is gone.
    society_id = resident.society_id
    flat_number = resident.flat_number

    db.delete(resident)
    db.flush()

    # If the household still has members, one of them must be the contact —
    # promote the deterministic successor if we just removed the primary.
    resolve.ensure_primary(db, society_id, flat_number)
    return Response(status_code=204)
