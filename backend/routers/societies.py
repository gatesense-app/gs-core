from fastapi import APIRouter, Depends
from sqlalchemy import select

from backend import db_models as m
from backend.deps import get_db, require_role
from backend.schemas import SocietyCreate, SocietyResponse
from backend.security import hash_password

router = APIRouter(prefix="/societies", tags=["societies"])


@router.post("", status_code=201, response_model=SocietyResponse)
def create_society(
    body: SocietyCreate,
    _=Depends(require_role("platform_admin")),
    db=Depends(get_db),
):
    society = m.Society(name=body.name, address=body.address)
    db.add(society)
    db.flush()  # populates society.id (RETURNING)

    db.add(
        m.User(
            society_id=society.id,
            email=body.admin_email.lower(),
            password_hash=hash_password(body.admin_password),
            role="society_admin",
            full_name=body.admin_name,
        )
    )
    db.flush()
    return SocietyResponse(id=str(society.id), name=society.name, address=society.address)


@router.get("", response_model=list[SocietyResponse])
def list_societies(
    _=Depends(require_role("platform_admin", "society_admin")),
    db=Depends(get_db),
):
    rows = db.execute(select(m.Society).order_by(m.Society.created_at)).scalars().all()
    return [
        SocietyResponse(id=str(s.id), name=s.name, address=s.address, created_at=s.created_at)
        for s in rows
    ]
