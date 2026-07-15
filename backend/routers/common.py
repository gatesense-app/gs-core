"""Small shared helpers for the admin routers."""

import uuid

from fastapi import HTTPException

from backend.deps import CurrentUser


def parse_uuid(val: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid id format")


def resolve_society_id(user: CurrentUser, body_society_id: str | None) -> str:
    """
    Never trust a client-supplied society_id for scoped roles — a society_admin
    always writes into their own society (from the JWT). Only platform_admin may
    target an arbitrary society, and must name it.
    """
    if user.role == "platform_admin":
        if not body_society_id:
            raise HTTPException(422, "society_id is required for platform_admin")
        return body_society_id
    return user.society_id
