"""
Resident self-service API.

Everything here is scoped twice: RLS narrows to the caller's society, and every
query additionally narrows to the flat behind the caller's own Resident row (see
deps.get_current_resident). A resident can therefore never read or change another
flat's visitors or rules, even within their own society.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from backend import db_models as m
from backend.deps import get_current_resident, get_db
from backend.pipeline import serialize
from backend.schemas import PortalMeResponse, PortalRulesUpdate
from backend.tools import resolve

router = APIRouter(prefix="/portal", tags=["portal"])


def _to_me(db, r: m.Resident) -> PortalMeResponse:
    """
    Show the rules that actually apply at this resident's door.

    Since E6-S3 the agents read the *flat's* rules when it has any, so echoing
    this resident's own row back would show them settings the gate ignores.
    """
    resolved = resolve.resolve_rules(db, r.society_id, r.flat_number)
    return PortalMeResponse(
        resident_id=str(r.id),
        flat_number=r.flat_number,
        name=r.name,
        phone=r.phone,
        standing_rules=resolved["standing_rules"],
        delivery_preferences=resolved["delivery_preferences"],
    )


@router.get("/me", response_model=PortalMeResponse)
def portal_me(resident: m.Resident = Depends(get_current_resident), db=Depends(get_db)):
    """The caller's own flat, standing rules and delivery preferences."""
    return _to_me(db, resident)


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
    Update the standing rules / delivery preferences for the caller's door.

    Only these two fields are settable here — flat_number and name stay
    admin-managed.

    Writes land on the *flat* once the resident is linked to one (E6-S3), and on
    the resident's own row otherwise. Two things force this: rules are resolved
    per flat, so writing to the resident row would be a silent no-op at the gate
    for any flat with its own rules; and a shared flat has one door, so a
    housemate changing "never allow after 21:00" must change it for the door
    rather than for themselves alone.
    """
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "Nothing to update")

    target = db.get(m.Flat, resident.flat_id) if resident.flat_id else None
    for key, value in fields.items():
        setattr(target or resident, key, value)
    db.flush()
    return _to_me(db, resident)
