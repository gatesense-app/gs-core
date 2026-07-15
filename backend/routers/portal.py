"""
Resident self-service API.

Everything here is scoped twice: RLS narrows to the caller's society, and every
query additionally narrows to the flat behind the caller's own Resident row (see
deps.get_current_resident). A resident can therefore never read or change another
flat's visitors or rules, even within their own society.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend import db_models as m
from backend.deps import get_current_resident, get_db
from backend.pipeline import serialize
from backend.schemas import PortalMeResponse, PortalRulesUpdate

router = APIRouter(prefix="/portal", tags=["portal"])


def _to_me(r: m.Resident) -> PortalMeResponse:
    return PortalMeResponse(
        resident_id=str(r.id),
        flat_number=r.flat_number,
        name=r.name,
        phone=r.phone,
        standing_rules=r.standing_rules or [],
        delivery_preferences=r.delivery_preferences or {},
    )


@router.get("/me", response_model=PortalMeResponse)
def portal_me(resident: m.Resident = Depends(get_current_resident)):
    """The caller's own flat, standing rules and delivery preferences."""
    return _to_me(resident)


@router.get("/sessions")
def portal_sessions(
    resident: m.Resident = Depends(get_current_resident),
    db=Depends(get_db),
):
    """Visitor sessions for the caller's own flat only (newest first)."""
    rows = db.execute(
        select(m.VisitorSession)
        .where(m.VisitorSession.flat_number == resident.flat_number)
        .order_by(m.VisitorSession.entry_time.desc())
    ).scalars().all()
    return [serialize(r) for r in rows]


@router.patch("/rules", response_model=PortalMeResponse)
def update_own_rules(
    body: PortalRulesUpdate,
    resident: m.Resident = Depends(get_current_resident),
    db=Depends(get_db),
):
    """
    Update the caller's own standing rules / delivery preferences. Only these two
    fields are settable here — flat_number and name stay admin-managed.
    """
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(resident, key, value)
    db.flush()
    return _to_me(resident)
