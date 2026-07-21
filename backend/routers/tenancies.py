"""
Tenancy agreements for tenant-occupied flats.

A tenant-occupied flat (Flat.occupancy == 'tenant') runs a *tenancy*: the period
a set of tenants lives there. Tenants are ordinary residents (role='tenant')
linked to the tenancy, so the gate reaches them through the same primary-contact
machinery as everyone else — the primary tenant takes precedence over the flat's
owner while the tenancy is active.

Lifecycle:
  - start   — open a tenancy on a tenant-occupied flat (dates optional).
  - add     — add tenants; the first becomes the contact.
  - renew   — clone into a fresh tenancy with new dates (the old one is superseded
              and its tenants soft-deleted; the people are copied over).
  - end     — terminate early: soft-delete the tenants and revert the flat to
              owner-occupied, so the gate reaches the owner again.

Ending never destroys anything — tenants keep their rows (and the timeline keeps
every event), they're just soft-deleted so the gate stops reaching them.
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from backend import audit
from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid
from backend.routers.residents import _to_resp
from backend.schemas import (
    TenancyCreate,
    TenancyRenew,
    TenancyResponse,
    TenantCreate,
)
from backend.tools import resolve

router = APIRouter(tags=["tenancies"])

_admins = require_role("platform_admin", "society_admin")


def _now():
    return datetime.now(timezone.utc)


def _get_flat(db, flat_id: str) -> m.Flat:
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None or flat.deleted_at is not None:  # RLS/soft-delete -> 404
        raise HTTPException(404, "Flat not found")
    return flat


def _get_tenancy(db, tenancy_id: str) -> m.Tenancy:
    t = db.get(m.Tenancy, parse_uuid(tenancy_id))
    if t is None or t.deleted_at is not None:
        raise HTTPException(404, "Tenancy not found")
    return t


def _active_tenancy(db, flat_id):
    return db.execute(
        select(m.Tenancy).where(
            m.Tenancy.flat_id == flat_id,
            m.Tenancy.ended_at.is_(None),
            m.Tenancy.deleted_at.is_(None),
        )
    ).scalars().first()


def _tenants_of(db, tenancy_id, *, live_only: bool):
    """Tenants of a tenancy, primary first. History wants the deleted ones too."""
    q = select(m.Resident).where(m.Resident.tenancy_id == tenancy_id)
    if live_only:
        q = q.where(m.Resident.deleted_at.is_(None))
    q = q.order_by(
        m.Resident.is_primary.desc(),
        m.Resident.created_at.asc(),
        m.Resident.id.asc(),
    )
    return list(db.execute(q).scalars().all())


def _status(t: m.Tenancy) -> str:
    if t.ended_at is not None:
        return "ended"
    if t.end_date is not None and t.end_date < date.today():
        return "expired"  # still active (gate unchanged) but past its agreement
    return "active"


def _tenancy_resp(db, t: m.Tenancy) -> TenancyResponse:
    # A live (active) tenancy lists its live tenants; an ended one keeps showing
    # the tenants it had, soft-deleted, for history.
    live = t.ended_at is None
    tenants = _tenants_of(db, t.id, live_only=live)
    return TenancyResponse(
        id=str(t.id),
        flat_id=str(t.flat_id),
        flat_code=t.flat_code,
        start_date=t.start_date,
        end_date=t.end_date,
        ended_at=t.ended_at,
        status=_status(t),
        prior_tenancy_id=str(t.prior_tenancy_id) if t.prior_tenancy_id else None,
        tenants=[_to_resp(r) for r in tenants],
    )


def _supersede(db, t: m.Tenancy) -> list[m.Resident]:
    """
    Close an active tenancy: mark it ended and soft-delete its live tenants.

    Returns the tenants (captured before deletion) so a renewal can copy them.
    Shared by `renew` (the old tenancy is replaced) and `end` (it's terminated).
    """
    now = _now()
    tenants = _tenants_of(db, t.id, live_only=True)
    for r in tenants:
        r.deleted_at = now
        r.is_primary = False  # free the primary slot for the successor
    t.ended_at = now
    db.flush()
    return tenants


# ---------------------------------------------------------------------------
# Start / list
# ---------------------------------------------------------------------------
@router.post("/flats/{flat_id}/tenancies", status_code=201, response_model=TenancyResponse)
def start_tenancy(
    flat_id: str,
    body: TenancyCreate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """Open a tenancy on a tenant-occupied flat. Dates optional; one active at a time."""
    flat = _get_flat(db, flat_id)
    if flat.occupancy != "tenant":
        raise HTTPException(
            409, "This flat is owner-occupied. Switch occupancy to tenant first."
        )
    if _active_tenancy(db, flat.id) is not None:
        raise HTTPException(409, "This flat already has an active tenancy.")

    tenancy = m.Tenancy(
        society_id=flat.society_id, flat_id=flat.id, flat_code=flat.code,
        start_date=body.start_date, end_date=body.end_date,
    )
    db.add(tenancy)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, "This flat already has an active tenancy.")

    audit.record(
        db, society_id=flat.society_id, user=user, action="tenancy_started",
        summary=f"Tenancy started on {flat.code}" + _dates_phrase(tenancy),
        entity_type=audit.TENANCY, entity_id=tenancy.id,
        flat_id=flat.id, flat_code=flat.code,
        detail={"start_date": str(tenancy.start_date) if tenancy.start_date else None,
                "end_date": str(tenancy.end_date) if tenancy.end_date else None},
    )
    return _tenancy_resp(db, tenancy)


@router.get("/flats/{flat_id}/tenancies", response_model=list[TenancyResponse])
def list_tenancies(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """This flat's tenancies, active first then most-recently-ended."""
    flat = _get_flat(db, flat_id)
    rows = db.execute(
        select(m.Tenancy)
        .where(m.Tenancy.flat_id == flat.id, m.Tenancy.deleted_at.is_(None))
        # Active (ended_at IS NULL) first, then newest by creation.
        .order_by(m.Tenancy.ended_at.is_(None).desc(), m.Tenancy.created_at.desc())
    ).scalars().all()
    return [_tenancy_resp(db, t) for t in rows]


# ---------------------------------------------------------------------------
# Add a tenant
# ---------------------------------------------------------------------------
@router.post("/tenancies/{tenancy_id}/tenants", status_code=201, response_model=TenancyResponse)
def add_tenant(
    tenancy_id: str,
    body: TenantCreate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """Add a tenant to the active tenancy. The first tenant becomes the contact."""
    t = _get_tenancy(db, tenancy_id)
    if t.ended_at is not None:
        raise HTTPException(409, "This tenancy has ended.")

    resident = m.Resident(
        society_id=t.society_id, flat_number=t.flat_code, flat_id=t.flat_id,
        tenancy_id=t.id, role="tenant",
        name=body.name.strip(), phone=body.phone,
        standing_rules=body.standing_rules, delivery_preferences=body.delivery_preferences,
    )
    db.add(resident)
    db.flush()
    # Occupancy is 'tenant', so this draws the contact from the tenant pool.
    resolve.resync_primary(db, t.society_id, t.flat_code)
    audit.record(
        db, society_id=t.society_id, user=user, action="resident_added",
        summary=f"{resident.name} added as tenant on {t.flat_code}",
        entity_type=audit.RESIDENT, entity_id=resident.id,
        flat_id=t.flat_id, flat_code=t.flat_code,
    )
    return _tenancy_resp(db, t)


# ---------------------------------------------------------------------------
# Renew (clone) / end
# ---------------------------------------------------------------------------
@router.post("/tenancies/{tenancy_id}/renew", status_code=201, response_model=TenancyResponse)
def renew_tenancy(
    tenancy_id: str,
    body: TenancyRenew,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    """
    Renew: clone the tenancy into a fresh one with new dates.

    The old tenancy is superseded (its tenants soft-deleted for history) and the
    same people are copied into the new one, keeping who was the primary contact.
    The flat stays tenant-occupied.
    """
    old = _get_tenancy(db, tenancy_id)
    if old.ended_at is not None:
        raise HTTPException(409, "This tenancy has already ended.")
    flat = _get_flat(db, str(old.flat_id))

    # Capture + close the old one first: the unique index allows only one active
    # tenancy per flat, so the new row can't coexist with an un-ended old one.
    old_primary_name = next((r.name for r in _tenants_of(db, old.id, live_only=True)
                             if r.is_primary), None)
    carried = _supersede(db, old)

    new = m.Tenancy(
        society_id=flat.society_id, flat_id=flat.id, flat_code=flat.code,
        start_date=body.start_date, end_date=body.end_date, prior_tenancy_id=old.id,
    )
    db.add(new)
    db.flush()

    for r in carried:
        copy = m.Resident(
            society_id=flat.society_id, flat_number=flat.code, flat_id=flat.id,
            tenancy_id=new.id, role="tenant", name=r.name, phone=r.phone,
            standing_rules=r.standing_rules, delivery_preferences=r.delivery_preferences,
        )
        db.add(copy)
        db.flush()
        audit.record(
            db, society_id=flat.society_id, user=user, action="resident_added",
            summary=f"{copy.name} carried over to the renewed tenancy on {flat.code}",
            entity_type=audit.RESIDENT, entity_id=copy.id,
            flat_id=flat.id, flat_code=flat.code,
        )
        if r.name == old_primary_name:
            resolve.claim_primary(db, copy)

    resolve.resync_primary(db, flat.society_id, flat.code)
    audit.record(
        db, society_id=flat.society_id, user=user, action="tenancy_renewed",
        summary=f"Tenancy renewed on {flat.code}" + _dates_phrase(new)
        + f", carrying over {len(carried)} tenant(s)",
        entity_type=audit.TENANCY, entity_id=new.id,
        flat_id=flat.id, flat_code=flat.code,
        detail={"prior_tenancy_id": str(old.id),
                "start_date": str(new.start_date) if new.start_date else None,
                "end_date": str(new.end_date) if new.end_date else None},
    )
    return _tenancy_resp(db, new)


@router.post("/tenancies/{tenancy_id}/end", status_code=200, response_model=TenancyResponse)
def end_tenancy(tenancy_id: str, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    """
    End a tenancy early. Soft-deletes its tenants and reverts the flat to
    owner-occupied, so the gate reaches the owner again.
    """
    t = _get_tenancy(db, tenancy_id)
    if t.ended_at is not None:
        raise HTTPException(409, "This tenancy has already ended.")
    flat = _get_flat(db, str(t.flat_id))

    tenants = _supersede(db, t)
    old_occupancy = flat.occupancy
    flat.occupancy = "owner"  # decision: ending reverts to owner-occupied
    db.flush()

    for r in tenants:
        audit.record(
            db, society_id=t.society_id, user=user, action="resident_deleted",
            summary=f"{r.name} removed (tenancy on {t.flat_code} ended)",
            entity_type=audit.RESIDENT, entity_id=r.id,
            flat_id=t.flat_id, flat_code=t.flat_code,
        )
    audit.record(
        db, society_id=t.society_id, user=user, action="tenancy_ended",
        summary=f"Tenancy on {t.flat_code} ended, with {len(tenants)} tenant(s)",
        entity_type=audit.TENANCY, entity_id=t.id,
        flat_id=t.flat_id, flat_code=t.flat_code,
        detail={"tenants_removed": len(tenants)},
    )
    if old_occupancy != "owner":
        audit.record(
            db, society_id=t.society_id, user=user, action="flat_occupancy_changed",
            summary=f"Occupancy changed from {old_occupancy} to owner (tenancy ended)",
            entity_type=audit.FLAT, entity_id=flat.id,
            flat_id=flat.id, flat_code=flat.code,
            detail={"from": old_occupancy, "to": "owner"},
        )

    # The owner is the contact again.
    before = resolve.primary_resident(db, t.society_id, t.flat_code)
    before_id = before.id if before is not None else None
    promoted = resolve.resync_primary(db, t.society_id, t.flat_code)
    if promoted is not None and promoted.id != before_id:
        audit.record(
            db, society_id=t.society_id, user=user, action="resident_primary_set",
            summary=f"{promoted.name} became the primary contact (owner-occupied)",
            entity_type=audit.RESIDENT, entity_id=promoted.id,
            flat_id=flat.id, flat_code=flat.code,
        )
    return _tenancy_resp(db, t)


def _dates_phrase(t: m.Tenancy) -> str:
    if t.start_date and t.end_date:
        return f" ({t.start_date} to {t.end_date})"
    if t.start_date:
        return f" (from {t.start_date})"
    if t.end_date:
        return f" (until {t.end_date})"
    return ""
