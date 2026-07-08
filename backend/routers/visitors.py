from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import resolve_society_id
from backend.schemas import VisitorCreate, VisitorResponse

router = APIRouter(prefix="/visitors", tags=["visitors"])

_admins = require_role("platform_admin", "society_admin")


def _to_resp(v: m.Visitor) -> VisitorResponse:
    return VisitorResponse(
        id=str(v.id),
        society_id=str(v.society_id),
        name=v.name,
        flat_number=v.flat_number,
        visitor_type=v.visitor_type,
        is_known_service=v.is_known_service,
        visit_count=v.visit_count,
        notes=v.notes,
    )


@router.get("", response_model=list[VisitorResponse])
def list_visitors(_: CurrentUser = Depends(_admins), db=Depends(get_db)):
    rows = db.execute(select(m.Visitor).order_by(m.Visitor.name)).scalars().all()
    return [_to_resp(v) for v in rows]


@router.post("", status_code=201, response_model=VisitorResponse)
def create_visitor(body: VisitorCreate, user: CurrentUser = Depends(_admins), db=Depends(get_db)):
    society_id = resolve_society_id(user, body.society_id)
    visitor = m.Visitor(
        society_id=society_id,
        name=body.name,
        flat_number=body.flat_number,
        visitor_type=body.visitor_type,
        phone=body.phone,
        is_known_service=body.is_known_service,
        visit_count=body.visit_count,
        typical_hours=body.typical_hours,
        notes=body.notes,
    )
    db.add(visitor)
    db.flush()
    return _to_resp(visitor)
