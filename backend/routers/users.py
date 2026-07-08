from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from backend import db_models as m
from backend.deps import CurrentUser, get_db, require_role
from backend.routers.common import parse_uuid, resolve_society_id
from backend.schemas import UserCreate, UserResponse
from backend.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

_admins = require_role("platform_admin", "society_admin")


def _to_resp(u: m.User) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        email=u.email,
        role=u.role,
        full_name=u.full_name,
        society_id=str(u.society_id) if u.society_id else None,
        is_active=u.is_active,
    )


@router.get("", response_model=list[UserResponse])
def list_users(_: CurrentUser = Depends(_admins), db=Depends(get_db)):
    rows = db.execute(select(m.User).order_by(m.User.email)).scalars().all()
    return [_to_resp(u) for u in rows]


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
    return _to_resp(new_user)
