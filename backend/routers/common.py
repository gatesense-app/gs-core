"""Small shared helpers for the admin routers."""

import uuid

from fastapi import HTTPException

from backend.deps import CurrentUser


def normalize_phone(raw: str | None) -> str | None:
    """
    Canonical form of a phone number for storage + login lookup.

    Strips spaces, dashes, parentheses and dots so a resident typing "+91 98…"
    matches the stored "+9198…". Kept deliberately loose (no country-code logic):
    both the provisioning write and the login read run through here, so as long as
    they agree the exact shape doesn't matter. Returns None for an empty value.
    """
    if not raw:
        return None
    cleaned = "".join(c for c in raw if c.isdigit() or c == "+")
    return cleaned or None


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
