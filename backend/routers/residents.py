from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from backend import audit
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


def _flat_id_for(db, society_id, flat_number):
    """The live flat this resident sits on, for pinning an event to a timeline."""
    flat = resolve.flat_for(db, society_id, flat_number)
    return flat.id if flat is not None else None


def _record_primary_if_changed(db, user, society_id, flat_number, before_id):
    """After a change that could re-elect a contact, log it if the winner changed."""
    now_primary = resolve.primary_resident(db, society_id, flat_number)
    if now_primary is not None and now_primary.id != before_id:
        audit.record(
            db, society_id=society_id, user=user, action="resident_primary_set",
            summary=f"{now_primary.name} became the primary contact",
            entity_type=audit.RESIDENT, entity_id=now_primary.id,
            flat_id=_flat_id_for(db, society_id, flat_number), flat_code=flat_number,
        )


@router.get("", response_model=list[ResidentResponse])
def list_residents(_: CurrentUser = Depends(_admins), db=Depends(get_db)):
    rows = db.execute(
        select(m.Resident)
        .where(m.Resident.deleted_at.is_(None))
        .order_by(m.Resident.flat_number)
    ).scalars().all()
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
    audit.record(
        db, society_id=society_id, user=user, action="resident_added",
        summary=f"{resident.name} added to {resident.flat_number}",
        entity_type=audit.RESIDENT, entity_id=resident.id,
        flat_id=_flat_id_for(db, society_id, resident.flat_number),
        flat_code=resident.flat_number,
    )
    return _to_resp(resident)


@router.get("/{resident_id}", response_model=ResidentResponse)
def get_resident(resident_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    resident = db.get(m.Resident, parse_uuid(resident_id))
    if resident is None or resident.deleted_at is not None:  # hidden -> 404
        raise HTTPException(404, "Resident not found")
    return _to_resp(resident)


@router.patch("/{resident_id}", response_model=ResidentResponse)
def update_resident(
    resident_id: str,
    body: ResidentUpdate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    resident = db.get(m.Resident, parse_uuid(resident_id))
    if resident is None or resident.deleted_at is not None:
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
    before = {"name": resident.name, "phone": resident.phone, "flat_number": old_flat_number}
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

    # One event for the field edit, one for a primary hand-over — they're
    # different facts a reader of the timeline cares about separately.
    changed = {k: v for k, v in fields.items() if before.get(k) != v}
    if changed:
        bits = []
        if "name" in changed:
            bits.append(f"name → {resident.name}")
        if "phone" in changed:
            bits.append("phone updated")
        if "flat_number" in changed:
            bits.append(f"moved to {resident.flat_number}")
        audit.record(
            db, society_id=resident.society_id, user=user, action="resident_edited",
            summary=f"{resident.name}: " + ", ".join(bits),
            entity_type=audit.RESIDENT, entity_id=resident.id,
            flat_id=_flat_id_for(db, resident.society_id, resident.flat_number),
            flat_code=resident.flat_number,
            detail={"before": before, "after": {**before, **changed}},
        )
    if want_primary:
        audit.record(
            db, society_id=resident.society_id, user=user, action="resident_primary_set",
            summary=f"{resident.name} made the primary contact",
            entity_type=audit.RESIDENT, entity_id=resident.id,
            flat_id=_flat_id_for(db, resident.society_id, resident.flat_number),
            flat_code=resident.flat_number,
        )
    return _to_resp(resident)


@router.delete("/{resident_id}", status_code=204)
def delete_resident(resident_id: str, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    resident = db.get(m.Resident, parse_uuid(resident_id))
    if resident is None or resident.deleted_at is not None:  # hidden -> 404
        raise HTTPException(404, "Resident not found")

    # Soft delete: keep the row (and its history), just mark it gone. resolve.py
    # filters deleted_at, so the gate stops reaching this person immediately.
    society_id = resident.society_id
    flat_number = resident.flat_number
    name = resident.name
    was_primary = resident.is_primary

    resident.deleted_at = datetime.now(timezone.utc)
    resident.is_primary = False  # free the primary slot for a live successor
    db.flush()

    audit.record(
        db, society_id=society_id, user=user, action="resident_deleted",
        summary=f"{name} removed from {flat_number}",
        entity_type=audit.RESIDENT, entity_id=resident.id,
        flat_id=_flat_id_for(db, society_id, flat_number), flat_code=flat_number,
    )

    # If the household still has members, one of them must be the contact.
    if was_primary:
        promoted = resolve.ensure_primary(db, society_id, flat_number)
        if promoted is not None:
            audit.record(
                db, society_id=society_id, user=user, action="resident_primary_set",
                summary=f"{promoted.name} became the primary contact",
                entity_type=audit.RESIDENT, entity_id=promoted.id,
                flat_id=_flat_id_for(db, society_id, flat_number), flat_code=flat_number,
            )
    return Response(status_code=204)
