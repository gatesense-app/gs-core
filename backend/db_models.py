"""
SQLAlchemy ORM models — the multi-tenant schema.

Every tenant table carries `society_id` (or, for `societies` itself, its own
`id`) and has a Postgres RLS policy keyed on it (added in the initial Alembic
migration). `users.society_id` is nullable: platform_admin users belong to no
society.

Runtime pipeline tables (visitor_sessions, conversation_log, escalations,
notification_delivery_log) are defined here so the schema + RLS are complete,
but their write paths are wired up in Phases 2–4.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from backend.db import Base

_UUID = UUID(as_uuid=True)


def _pk():
    return Column(_UUID, primary_key=True, server_default=text("gen_random_uuid()"))


def _created_at():
    return Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class Society(Base):
    __tablename__ = "societies"

    id = _pk()
    name = Column(String(200), nullable=False)
    address = Column(Text)
    created_at = _created_at()


class Wing(Base):
    """
    A wing/building: the *declared shape* of a slice of the property (D6).

    `floors` and `flats_per_floor` describe the grid the UI draws; they create no
    flats and are only a hint (Q2). Real properties put shops on the ground floor
    and a penthouse on top, so a mismatch warns and saves — it never rejects.
    Total flats is always counted from `flats`, never `floors * flats_per_floor`.
    """

    __tablename__ = "wings"
    __table_args__ = (
        # The name is part of every flat code, so a duplicate would make codes ambiguous.
        UniqueConstraint("society_id", "name", name="uq_wings_society_name"),
    )

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(64), nullable=False)
    floors = Column(Integer, nullable=False)
    flats_per_floor = Column(Integer, nullable=False)
    created_at = _created_at()


class Flat(Base):
    """
    A real flat (D1). `code` is typed or imported, never generated (D2).

    Two deliberate denormalizations:
      - `code` is stored even though it's "{wing}-{flat_number}" at creation time,
        so the guard's typed string resolves in one indexed lookup, and so a wing
        rename can't silently rewrite history (E4-S3).
      - `floor` is stored, never parsed from the code (Q1) — a typed `A-101`
        carries no floor, and the first society that names flats differently
        would break any derivation.
    """

    __tablename__ = "flats"
    __table_args__ = (
        # Partial: a soft-deleted flat keeps its row (for history) but frees its
        # code, so the same A-101 can be created again later. Without the
        # deleted_at filter the deleted row would forever block re-use.
        Index(
            "uq_flats_society_code",
            "society_id", "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    wing_id = Column(_UUID, ForeignKey("wings.id", ondelete="CASCADE"), nullable=False)
    flat_number = Column(String(32), nullable=False)
    floor = Column(Integer, nullable=False)
    code = Column(String(64), nullable=False)
    # Soft delete: deleting a flat sets this rather than removing the row, so its
    # history (and its residents') is never lost. Every user-facing read filters
    # deleted_at IS NULL; resolve.py does too, so the gate never reaches a
    # deleted flat. See backend/audit.py for the trail.
    deleted_at = Column(DateTime(timezone=True))
    # When a flat is re-created with the same code as a soft-deleted one, the admin
    # may choose to link the new flat to that prior deleted flat, so its history
    # (and its former, now-deleted residents) surfaces on the new flat's timeline.
    # Self-referential and nullable; a fresh (unlinked) flat leaves it NULL. The
    # link is a memory-only pointer — the deleted rows stay deleted (the gate never
    # sees them); only the timeline walks the chain. See routers/layout.py.
    prior_flat_id = Column(_UUID, ForeignKey("flats.id", ondelete="SET NULL"))
    # E6-S3: rules belong to the door, not to whoever happens to live behind it —
    # two residents must not hold contradictory rules for one flat.
    #
    # Deliberately NULLABLE, unlike the residents columns: NULL means "not set,
    # fall back to the primary resident", which is different from [] meaning
    # "explicitly no rules". A [] default would make a society's first reconcile
    # silently overrule every resident's real rules — a gate behaviour change
    # delivered by a migration.
    standing_rules = Column(JSONB)
    delivery_preferences = Column(JSONB)
    created_at = _created_at()


class Resident(Base):
    """
    A person behind a flat. Several per flat is normal (D3), so exactly one of
    them is the flat's primary contact — the person the agents actually reach.
    """

    __tablename__ = "residents"
    __table_args__ = (
        # At most one *live* primary per flat, enforced by Postgres rather than
        # by hope. Keyed on flat_number (not flat_id) because it must hold in
        # both worlds: today nearly every resident has flat_id NULL, and the
        # agents resolve on this string until the layout is reconciled. The
        # deleted_at clause lets a soft-deleted primary step aside for a live one.
        Index(
            "uq_residents_primary_per_flat",
            "society_id", "flat_number",
            unique=True,
            postgresql_where=text("is_primary AND deleted_at IS NULL"),
        ),
    )

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    flat_number = Column(String(32), nullable=False)
    # Nullable: the existing free-text residents are linked by E4-S4 (reconcile).
    # Requiring it now would break the seed and every existing test.
    flat_id = Column(_UUID, ForeignKey("flats.id", ondelete="SET NULL"))
    name = Column(String(200), nullable=False)
    phone = Column(String(32))
    # E6-S3 / Q3: the flat's contact, defaulting to the first resident added.
    # Never rely on "whichever row the database returned first".
    is_primary = Column(Boolean, nullable=False, server_default=text("false"))
    # e.g. [{"type": "always_allow", "match": "Swiggy"}, {"type": "never_allow", "after": "21:00"}]
    # A flat's own rules win over these when set (see tools/resolve.py).
    standing_rules = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # e.g. {"auto_log_daytime": true, "notify_after_hours": true}
    delivery_preferences = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Soft delete: removing a resident sets this, keeping the row for history.
    # resolve.py filters it out, so a removed resident is invisible to the gate.
    deleted_at = Column(DateTime(timezone=True))
    created_at = _created_at()


class User(Base):
    __tablename__ = "users"

    id = _pk()
    # NULL for platform_admin (belongs to no society)
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"))
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), nullable=False)  # platform_admin|society_admin|guard|resident
    full_name = Column(String(200))
    resident_id = Column(_UUID, ForeignKey("residents.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = _created_at()


class Visitor(Base):
    """Known visitors + synthetic history (feeds lookup_visitor_history)."""

    __tablename__ = "visitors"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    flat_number = Column(String(32))  # flat this visitor is typically associated with
    visitor_type = Column(String(32))  # guest|delivery|service|cab|other
    phone = Column(String(32))
    is_known_service = Column(Boolean, nullable=False, server_default=text("false"))
    visit_count = Column(Integer, nullable=False, server_default=text("0"))
    last_visit_at = Column(DateTime(timezone=True))
    typical_hours = Column(JSONB)  # {"start": "09:00", "end": "18:00"}
    notes = Column(Text)
    created_at = _created_at()


class VisitorSession(Base):
    """A live gate-entry session (written by the pipeline in Phases 2–5)."""

    __tablename__ = "visitor_sessions"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    visitor_name = Column(String(200), nullable=False)
    flat_number = Column(String(32), nullable=False)
    purpose = Column(String(32))
    purpose_detail = Column(Text)
    status = Column(String(32), nullable=False, server_default=text("'pending'"))
    resolved_by = Column(String(32))
    resolved_at = Column(DateTime(timezone=True))
    entry_time = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    decision_trace = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    conversation_history = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at = _created_at()


class ConversationLog(Base):
    __tablename__ = "conversation_log"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(_UUID, ForeignKey("visitor_sessions.id", ondelete="CASCADE"), nullable=False)
    turn_number = Column(Integer)
    speaker = Column(String(32))  # agent|resident|guard
    message = Column(Text)
    created_at = _created_at()


class Escalation(Base):
    __tablename__ = "escalations"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(_UUID, ForeignKey("visitor_sessions.id", ondelete="CASCADE"), nullable=False)
    reason = Column(Text)
    escalated_to = Column(String(64))  # backup_contact|guard_default
    status = Column(String(32), nullable=False, server_default=text("'open'"))
    created_at = _created_at()


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_log"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(_UUID, ForeignKey("visitor_sessions.id", ondelete="CASCADE"))
    resident_id = Column(_UUID, ForeignKey("residents.id", ondelete="SET NULL"))
    channel = Column(String(16), nullable=False, server_default=text("'in_app'"))
    status = Column(String(16))  # sent|delivered|failed
    provider_message_id = Column(String(255))
    created_at = _created_at()


class LayoutEvent(Base):
    """
    An append-only record of a change to a flat or its residents (the timeline).

    Immutable by convention: rows are inserted, never updated or deleted, so the
    history stays trustworthy. Actor and flat code are *snapshotted* onto the row
    rather than joined at read time — the admin who acted may later be removed,
    and a flat's code can change, but "who did what, and to which flat, when"
    must still read correctly years later.

    `flat_id` / `entity_id` carry no foreign keys on purpose: an event outlives
    what it describes, and a FK would either block a future hard cleanup or drag
    the event down with a CASCADE. The rows are soft-deleted anyway, so the
    references stay resolvable in practice.
    """

    __tablename__ = "layout_events"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    # The flat this event belongs to on its timeline (may be a resident action).
    flat_id = Column(_UUID)
    flat_code = Column(String(64))  # snapshot, so the timeline reads after a rename
    entity_type = Column(String(16), nullable=False)  # flat | resident
    entity_id = Column(_UUID, nullable=False)
    action = Column(String(40), nullable=False)  # flat_created | resident_deleted | ...
    summary = Column(Text, nullable=False)       # human-readable, built server-side
    detail = Column(JSONB)                        # structured before/after, optional
    actor_user_id = Column(_UUID)                 # who did it (no FK: see docstring)
    actor_email = Column(String(255))             # snapshot of the actor's email
    created_at = _created_at()


# Tables that get RLS. `societies` filters on its own `id`; the rest on society_id.
TENANT_TABLES = [
    "societies",
    "wings",
    "flats",
    "residents",
    "layout_events",
    "users",
    "visitors",
    "visitor_sessions",
    "conversation_log",
    "escalations",
    "notification_delivery_log",
]
