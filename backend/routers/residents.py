from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid, resolve_society_id
from backend.schemas import ResidentCreate, ResidentResponse, ResidentUpdate

router = APIRouter(prefix="/residents", tags=["residents"])

_admins = require_role("platform_admin", "society_admin")


def _to_resp(r: m.Resident) -> ResidentResponse:
    return ResidentResponse(
        id=str(r.id),
        society_id=str(r.society_id),
        flat_number=r.flat_number,
        name=r.name,
        phone=r.phone,
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
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(resident, key, value)
    db.flush()
    return _to_resp(resident)
