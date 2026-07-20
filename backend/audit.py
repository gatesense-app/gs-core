"""
The layout timeline — an append-only record of what changed on a flat.

Every mutation to a flat or its residents (created, renamed, moved, rules
changed, resident added/edited/made-primary/removed) writes one row here, so the
flat detail page can answer "what happened to A-101, and who did it?" long after
the fact — including for flats and residents that have since been soft-deleted.

Two things are *snapshotted* onto the event rather than joined at read time:
  - the actor's email, because the admin who acted may later be removed;
  - the flat's code, because a rename changes it and history must still read.

`record` runs inside the caller's request transaction, so an event and the
change it describes commit together (or roll back together) — the log can't
drift from reality.
"""

import uuid

from backend import db_models as m

# Entity types
FLAT = "flat"
RESIDENT = "resident"


def _actor_email(db, user) -> tuple[uuid.UUID | None, str | None]:
    """
    Resolve the acting admin's id + email for the snapshot.

    The JWT carries the user id but not the email, so we look the row up once
    (the session identity map caches it, so repeated events in one request are
    free). A missing user — or a system path with no user — records as None.
    """
    if user is None:
        return None, None
    try:
        uid = uuid.UUID(str(user.user_id))
    except (ValueError, TypeError):
        return None, None
    row = db.get(m.User, uid)
    return uid, (row.email if row is not None else None)


def record(
    db,
    *,
    society_id,
    user,
    action: str,
    summary: str,
    entity_type: str,
    entity_id,
    flat_id=None,
    flat_code: str | None = None,
    detail: dict | None = None,
) -> m.LayoutEvent:
    """
    Append one immutable event. Returns it (rarely needed; mostly fire-and-log).

    `flat_id` is the flat this belongs to on the timeline — for a resident action
    it's the resident's flat, so the event surfaces on that flat's history. It may
    be None for a free-text resident with no flat yet; such an event simply has no
    flat timeline to appear on, which is correct.
    """
    actor_id, actor_email = _actor_email(db, user)
    event = m.LayoutEvent(
        society_id=society_id,
        flat_id=flat_id,
        flat_code=flat_code,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        summary=summary,
        detail=detail,
        actor_user_id=actor_id,
        actor_email=actor_email,
    )
    db.add(event)
    db.flush()
    return event
