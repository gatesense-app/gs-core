"""
FastAPI dependencies for auth + tenant-scoped DB access.

Two session flavours:

  scoped_session(society_id, bypass)  — SET ROLE app_rls + set the
      app.current_society_id / app.bypass_rls GUCs the RLS policies read.
      This is what normal authenticated requests use, so Postgres itself
      enforces that Society A can't read Society B.

  system_session()                    — plain superuser connection, RLS
      bypassed. Used only for pre-tenant operations: login lookup (find a
      user by email before we know their society), seeding, bootstrap.
"""

import uuid
from contextlib import contextmanager

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text

from backend import db_models as m
from backend.config import APP_DB_ROLE
from backend.db import SessionLocal
from backend.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


class CurrentUser:
    def __init__(self, user_id: str, society_id: str | None, role: str):
        self.user_id = user_id
        self.society_id = society_id
        self.role = role


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
@contextmanager
def scoped_session(society_id: str | None, bypass: bool = False):
    """Tenant-scoped session. RLS is enforced for the yielded session."""
    session = SessionLocal()
    try:
        session.execute(text(f"SET ROLE {APP_DB_ROLE}"))
        session.execute(
            text("SELECT set_config('app.bypass_rls', :b, false)"),
            {"b": "on" if bypass else "off"},
        )
        session.execute(
            text("SELECT set_config('app.current_society_id', :s, false)"),
            {"s": str(society_id) if society_id else ""},
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        # Reset before the connection returns to the pool so nothing leaks
        # into the next request that reuses this connection.
        try:
            session.execute(text("SELECT set_config('app.current_society_id', '', false)"))
            session.execute(text("SELECT set_config('app.bypass_rls', 'off', false)"))
            session.execute(text("RESET ROLE"))
            session.commit()
        except Exception:
            session.rollback()
        session.close()


@contextmanager
def system_session():
    """Superuser session, RLS bypassed. Login lookup, seeding, bootstrap only."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------
def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return CurrentUser(claims["sub"], claims.get("sid"), claims["role"])


def get_db(user: CurrentUser = Depends(get_current_user)):
    """Request-scoped, RLS-enforced DB session for the current user."""
    bypass = user.role == "platform_admin"
    with scoped_session(user.society_id, bypass=bypass) as session:
        yield session


def require_role(*roles: str):
    """Dependency factory: 403 unless the caller has one of `roles`."""

    def _dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return _dep


def resolve_resident_for_user(db, user: CurrentUser):
    """
    The Resident row behind a user (users.resident_id -> residents), or None.

    Resolved by lookup rather than a JWT claim, so re-linking a user takes effect
    immediately and no token migration is needed. `db` is RLS-scoped to the
    caller's society, so this can only ever reach their own society's rows.

    Used both by the resident-only gate below and by mixed-role endpoints that
    must narrow a resident to their own flat (see main.submit_reply).
    """
    row = db.get(m.User, uuid.UUID(user.user_id))
    if row is None or row.resident_id is None:
        return None
    return db.get(m.Resident, row.resident_id)


def get_current_resident(
    user: CurrentUser = Depends(require_role("resident")),
    db=Depends(get_db),
):
    """
    The Resident row behind a `resident` user. RLS scopes to the society, but a
    resident must only ever see their own flat — so every resident-facing query
    narrows on this row's flat_number.
    """
    resident = resolve_resident_for_user(db, user)
    if resident is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This resident account is not linked to a flat",
        )
    return resident
