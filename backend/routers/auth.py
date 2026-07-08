from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from backend import db_models as m
from backend.deps import CurrentUser, get_current_user, system_session
from backend.schemas import LoginRequest, MeResponse, TokenResponse
from backend.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    # Pre-tenant lookup: we don't know the society until we find the user.
    with system_session() as db:
        user = db.execute(
            select(m.User).where(m.User.email == body.email.lower())
        ).scalar_one_or_none()

        if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

        token = create_access_token(user_id=user.id, society_id=user.society_id, role=user.role)
        return TokenResponse(
            access_token=token,
            role=user.role,
            society_id=str(user.society_id) if user.society_id else None,
            full_name=user.full_name,
        )


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser = Depends(get_current_user)):
    return MeResponse(user_id=user.user_id, role=user.role, society_id=user.society_id)
