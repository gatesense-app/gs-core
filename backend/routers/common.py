"""Small shared helpers for the admin routers."""

import uuid

from fastapi import HTTPException

from backend.deps import CurrentUser


def normalize_phone(raw: str | None) -> str | None:
    """
    Canonical form of a phone number for storage + login lookup: the bare 10-digit
    mobile number, with any country code and formatting dropped.

    Keeps digits only, then takes the last 10 — so "+91 98000 00001", "9198000…"
    and "098000…" all reduce to the same "9800000001" a resident actually dials.
    Both the provisioning write and the login read run through here, so a resident
    signs in with just their 10-digit number. A value with fewer than 10 digits is
    kept as-is (nothing to trim); an empty value returns None.
    """
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    return digits[-10:] if len(digits) > 10 else digits


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
