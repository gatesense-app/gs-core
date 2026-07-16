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
        UniqueConstraint("society_id", "code", name="uq_flats_society_code"),
    )

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    wing_id = Column(_UUID, ForeignKey("wings.id", ondelete="CASCADE"), nullable=False)
    flat_number = Column(String(32), nullable=False)
    floor = Column(Integer, nullable=False)
    code = Column(String(64), nullable=False)
    created_at = _created_at()


class Resident(Base):
    __tablename__ = "residents"

    id = _pk()
    society_id = Column(_UUID, ForeignKey("societies.id", ondelete="CASCADE"), nullable=False)
    flat_number = Column(String(32), nullable=False)
    # Nullable: the existing free-text residents are linked by E4-S4 (reconcile).
    # Requiring it now would break the seed and every existing test.
    flat_id = Column(_UUID, ForeignKey("flats.id", ondelete="SET NULL"))
    name = Column(String(200), nullable=False)
    phone = Column(String(32))
    backup_contact_id = Column(_UUID, ForeignKey("residents.id", ondelete="SET NULL"))
    # e.g. [{"type": "always_allow", "match": "Swiggy"}, {"type": "never_allow", "after": "21:00"}]
    standing_rules = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # e.g. {"auto_log_daytime": true, "notify_after_hours": true}
    delivery_preferences = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
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


# Tables that get RLS. `societies` filters on its own `id`; the rest on society_id.
TENANT_TABLES = [
    "societies",
    "wings",
    "flats",
    "residents",
    "users",
    "visitors",
    "visitor_sessions",
    "conversation_log",
    "escalations",
    "notification_delivery_log",
]
