"""
Vehicle records and parking numbers for a flat.

Each flat keeps a list of vehicles (registration number, two/four-wheeler, and
the RC-book owner) and a list of parking numbers the society allotted to it. Both
are soft-deleted so a flat's history is never lost, and every change is reported
onto the flat's timeline (the same one residents/tenancy use).

Kept intentionally small for now: a vehicle is just its registration number,
type, and owner; a parking slot is just its number. Assigning a vehicle to a
specific slot is a later story.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from backend import audit
from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid
from backend.schemas import (
    ParkingCreate,
    ParkingResponse,
    VehicleCreate,
    VehicleResponse,
    VehicleUpdate,
)

router = APIRouter(tags=["vehicles"])

_admins = require_role("platform_admin", "society_admin")

_TYPE_LABEL = {"two_wheeler": "2-wheeler", "four_wheeler": "4-wheeler"}


def _now():
    return datetime.now(timezone.utc)


def _get_flat(db, flat_id: str) -> m.Flat:
    flat = db.get(m.Flat, parse_uuid(flat_id))
    if flat is None or flat.deleted_at is not None:  # RLS/soft-delete -> 404
        raise HTTPException(404, "Flat not found")
    return flat


def _vehicle_resp(v: m.Vehicle) -> VehicleResponse:
    return VehicleResponse(
        id=str(v.id), society_id=str(v.society_id), flat_id=str(v.flat_id),
        flat_code=v.flat_code, registration_number=v.registration_number,
        vehicle_type=v.vehicle_type, owner_name=v.owner_name,
    )


def _parking_resp(p: m.ParkingSlot) -> ParkingResponse:
    return ParkingResponse(
        id=str(p.id), society_id=str(p.society_id), flat_id=str(p.flat_id),
        flat_code=p.flat_code, parking_number=p.parking_number,
    )


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
@router.get("/flats/{flat_id}/vehicles", response_model=list[VehicleResponse])
def list_vehicles(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    flat = _get_flat(db, flat_id)
    rows = db.execute(
        select(m.Vehicle)
        .where(m.Vehicle.flat_id == flat.id, m.Vehicle.deleted_at.is_(None))
        .order_by(m.Vehicle.created_at.asc(), m.Vehicle.id.asc())
    ).scalars().all()
    return [_vehicle_resp(v) for v in rows]


@router.post("/flats/{flat_id}/vehicles", status_code=201, response_model=VehicleResponse)
def add_vehicle(
    flat_id: str,
    body: VehicleCreate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    flat = _get_flat(db, flat_id)
    reg = body.registration_number.strip().upper()
    # Checked up front for a clear message; the partial unique index is the guard.
    exists = db.execute(
        select(m.Vehicle.id).where(
            m.Vehicle.society_id == flat.society_id,
            m.Vehicle.registration_number == reg,
            m.Vehicle.deleted_at.is_(None),
        )
    ).first()
    if exists:
        raise HTTPException(409, f"Vehicle '{reg}' is already registered in this society")

    vehicle = m.Vehicle(
        society_id=flat.society_id, flat_id=flat.id, flat_code=flat.code,
        registration_number=reg, vehicle_type=body.vehicle_type,
        owner_name=body.owner_name.strip(),
    )
    db.add(vehicle)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, f"Vehicle '{reg}' is already registered in this society")

    audit.record(
        db, society_id=flat.society_id, user=user, action="vehicle_added",
        summary=f"{_TYPE_LABEL.get(vehicle.vehicle_type, vehicle.vehicle_type)} "
                f"{reg} added ({vehicle.owner_name})",
        entity_type=audit.VEHICLE, entity_id=vehicle.id,
        flat_id=flat.id, flat_code=flat.code,
    )
    return _vehicle_resp(vehicle)


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: str,
    body: VehicleUpdate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    vehicle = db.get(m.Vehicle, parse_uuid(vehicle_id))
    if vehicle is None or vehicle.deleted_at is not None:
        raise HTTPException(404, "Vehicle not found")

    fields = body.model_dump(exclude_unset=True)
    if "registration_number" in fields and fields["registration_number"]:
        fields["registration_number"] = fields["registration_number"].strip().upper()
    if "owner_name" in fields and fields["owner_name"]:
        fields["owner_name"] = fields["owner_name"].strip()
    changed = {k: v for k, v in fields.items() if getattr(vehicle, k) != v}
    if not changed:
        return _vehicle_resp(vehicle)

    for key, value in changed.items():
        setattr(vehicle, key, value)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, "That registration number already exists in this society")

    bits = []
    if "registration_number" in changed:
        bits.append(f"reg → {vehicle.registration_number}")
    if "vehicle_type" in changed:
        bits.append(f"type → {_TYPE_LABEL.get(vehicle.vehicle_type, vehicle.vehicle_type)}")
    if "owner_name" in changed:
        bits.append(f"owner → {vehicle.owner_name}")
    audit.record(
        db, society_id=vehicle.society_id, user=user, action="vehicle_edited",
        summary=f"{vehicle.registration_number}: " + ", ".join(bits),
        entity_type=audit.VEHICLE, entity_id=vehicle.id,
        flat_id=vehicle.flat_id, flat_code=vehicle.flat_code,
    )
    return _vehicle_resp(vehicle)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: str, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    vehicle = db.get(m.Vehicle, parse_uuid(vehicle_id))
    if vehicle is None or vehicle.deleted_at is not None:
        raise HTTPException(404, "Vehicle not found")
    vehicle.deleted_at = _now()  # soft delete — the record stays for history
    db.flush()
    audit.record(
        db, society_id=vehicle.society_id, user=user, action="vehicle_removed",
        summary=f"Vehicle {vehicle.registration_number} removed",
        entity_type=audit.VEHICLE, entity_id=vehicle.id,
        flat_id=vehicle.flat_id, flat_code=vehicle.flat_code,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Parking numbers
# ---------------------------------------------------------------------------
@router.get("/flats/{flat_id}/parking", response_model=list[ParkingResponse])
def list_parking(flat_id: str, _: CurrentUser = Depends(_admins), db=Depends(get_db)):
    flat = _get_flat(db, flat_id)
    rows = db.execute(
        select(m.ParkingSlot)
        .where(m.ParkingSlot.flat_id == flat.id, m.ParkingSlot.deleted_at.is_(None))
        .order_by(m.ParkingSlot.created_at.asc(), m.ParkingSlot.id.asc())
    ).scalars().all()
    return [_parking_resp(p) for p in rows]


@router.post("/flats/{flat_id}/parking", status_code=201, response_model=ParkingResponse)
def add_parking(
    flat_id: str,
    body: ParkingCreate,
    user: CurrentUser = Depends(_admins),
    db=Depends(get_db),
):
    flat = _get_flat(db, flat_id)
    number = body.parking_number.strip().upper()
    exists = db.execute(
        select(m.ParkingSlot).where(
            m.ParkingSlot.society_id == flat.society_id,
            m.ParkingSlot.parking_number == number,
            m.ParkingSlot.deleted_at.is_(None),
        )
    ).scalars().first()
    if exists:
        where = "this flat" if exists.flat_id == flat.id else f"flat {exists.flat_code}"
        raise HTTPException(409, f"Parking number '{number}' is already allotted to {where}")

    slot = m.ParkingSlot(
        society_id=flat.society_id, flat_id=flat.id, flat_code=flat.code,
        parking_number=number,
    )
    db.add(slot)
    try:
        db.flush()
    except Exception:
        raise HTTPException(409, f"Parking number '{number}' is already allotted")

    audit.record(
        db, society_id=flat.society_id, user=user, action="parking_added",
        summary=f"Parking {number} allotted",
        entity_type=audit.PARKING, entity_id=slot.id,
        flat_id=flat.id, flat_code=flat.code,
    )
    return _parking_resp(slot)


@router.delete("/parking/{parking_id}", status_code=204)
def delete_parking(parking_id: str, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    slot = db.get(m.ParkingSlot, parse_uuid(parking_id))
    if slot is None or slot.deleted_at is not None:
        raise HTTPException(404, "Parking number not found")
    slot.deleted_at = _now()
    db.flush()
    audit.record(
        db, society_id=slot.society_id, user=user, action="parking_removed",
        summary=f"Parking {slot.parking_number} released",
        entity_type=audit.PARKING, entity_id=slot.id,
        flat_id=slot.flat_id, flat_code=slot.flat_code,
    )
    return Response(status_code=204)
