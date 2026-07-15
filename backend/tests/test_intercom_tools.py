"""
Intercom tools are DB-backed and tenant-scoped. These tests hit the live
database (no Claude API) so they run cheaply in CI.

    python -m pytest backend/tests/test_intercom_tools.py -v
"""

import pytest
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.tools.intercom_tools import (
    IntercomContext,
    escalate_to_backup_contact,
    log_conversation_turn,
    send_notification,
    update_visitor_session,
)


@pytest.fixture
def society_with_session():
    """
    Society A: a resident (A-101) with a backup contact (A-102), plus a pending
    session awaiting the resident. Society B is separate for scoping checks.
    """
    ids = {}
    with system_session() as db:
        a = m.Society(name="IT-Test-A")
        b = m.Society(name="IT-Test-B")
        db.add_all([a, b])
        db.flush()

        backup = m.Resident(society_id=a.id, flat_number="A-102", name="Backup Person")
        db.add(backup)
        db.flush()
        db.add(m.Resident(
            society_id=a.id, flat_number="A-101", name="Priya Sharma",
            backup_contact_id=backup.id,
        ))
        db.add(m.Resident(society_id=b.id, flat_number="B-101", name="Arun Mehta"))

        session = m.VisitorSession(
            society_id=a.id, visitor_name="Vikram Nair", flat_number="A-101",
            purpose="guest", purpose_detail="Friend for dinner", status="awaiting_resident",
        )
        db.add(session)
        db.flush()
        ids["a"], ids["b"], ids["session"] = a.id, b.id, session.id

    yield ids

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name IN ('IT-Test-A', 'IT-Test-B')"))


def test_send_notification_persists_delivery_log(society_with_session):
    with scoped_session(society_with_session["a"]) as db:
        ctx = IntercomContext(db, society_with_session["a"], society_with_session["session"])
        res = send_notification(ctx, "A-101", "Priya Sharma", "Visitor at the gate")
        assert res["delivered"] is True

    with scoped_session(society_with_session["a"]) as db:
        n = db.execute(
            select(m.NotificationDeliveryLog).where(
                m.NotificationDeliveryLog.session_id == society_with_session["session"]
            )
        ).scalars().first()
        assert n is not None
        assert n.channel == "in_app"
        assert n.status == "sent"


def test_log_conversation_turn_persists(society_with_session):
    with scoped_session(society_with_session["a"]) as db:
        ctx = IntercomContext(db, society_with_session["a"], society_with_session["session"])
        log_conversation_turn(ctx, 1, "agent", "Hi Priya, a visitor is here")
        log_conversation_turn(ctx, 2, "resident", "ALLOW")

    with scoped_session(society_with_session["a"]) as db:
        rows = db.execute(
            select(m.ConversationLog)
            .where(m.ConversationLog.session_id == society_with_session["session"])
            .order_by(m.ConversationLog.turn_number)
        ).scalars().all()
        assert [r.speaker for r in rows] == ["agent", "resident"]


def test_update_visitor_session_sets_status(society_with_session):
    with scoped_session(society_with_session["a"]) as db:
        ctx = IntercomContext(db, society_with_session["a"], society_with_session["session"])
        update_visitor_session(ctx, "approved", resolved_by="resident")

    with scoped_session(society_with_session["a"]) as db:
        row = db.get(m.VisitorSession, society_with_session["session"])
        assert row.status == "approved"
        assert row.resolved_by == "resident"
        assert row.resolved_at is not None


def test_escalate_records_escalation_and_notifies_backup(society_with_session):
    with scoped_session(society_with_session["a"]) as db:
        ctx = IntercomContext(db, society_with_session["a"], society_with_session["session"])
        res = escalate_to_backup_contact(ctx, "Resident timed out")
        assert res["escalated"] is True
        assert res["backup_notified"] is True  # A-101 has a backup contact (A-102)

    with scoped_session(society_with_session["a"]) as db:
        esc = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == society_with_session["session"])
        ).scalars().first()
        assert esc is not None
        assert esc.escalated_to == "backup_contact"
        assert esc.status == "open"


def test_tools_are_tenant_scoped(society_with_session):
    # From Society B, A's session is invisible (RLS) so update touches nothing.
    with scoped_session(society_with_session["b"]) as db:
        ctx = IntercomContext(db, society_with_session["b"], society_with_session["session"])
        res = update_visitor_session(ctx, "approved", resolved_by="resident")
        assert res["success"] is True  # tool ran, but the row was not visible

    # The session in Society A is untouched — still awaiting_resident.
    with scoped_session(society_with_session["a"]) as db:
        row = db.get(m.VisitorSession, society_with_session["session"])
        assert row.status == "awaiting_resident"
