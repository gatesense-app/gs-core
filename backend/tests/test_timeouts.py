"""
Resident reply timeouts -> escalation, and durable intercom checkpoints.

Deterministic: timestamps are aged directly rather than sleeping, and no Claude
API is used. This is the "resident never replies" path — before it existed, such
a visitor waited at the gate forever.

    python -m pytest backend/tests/test_timeouts.py -v
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from backend import db_models as m
from backend.deps import scoped_session, system_session
from backend.timeouts import sweep_once


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def society():
    """A-101 has a backup contact (A-102); A-103 has none."""
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'TIMEOUT-Test'"))
        soc = m.Society(name="TIMEOUT-Test")
        db.add(soc)
        db.flush()
        backup = m.Resident(society_id=soc.id, flat_number="A-102", name="Backup Person")
        db.add(backup)
        db.flush()
        db.add(m.Resident(society_id=soc.id, flat_number="A-101", name="Priya Sharma",
                          backup_contact_id=backup.id))
        db.add(m.Resident(society_id=soc.id, flat_number="A-103", name="Lonely Resident"))
        db.flush()
        sid = soc.id
    yield sid
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'TIMEOUT-Test'"))


def _make_session(society_id, flat="A-101", *, status="awaiting_resident", age_minutes=0):
    """Create a session whose entry_time is `age_minutes` in the past."""
    with system_session() as db:
        row = m.VisitorSession(
            society_id=society_id, visitor_name="Vikram Nair", flat_number=flat,
            purpose="guest", purpose_detail="Dinner", status=status,
            entry_time=_now() - timedelta(minutes=age_minutes),
        )
        db.add(row)
        db.flush()
        return row.id


def test_silent_resident_escalates_to_backup_contact(society):
    sid = _make_session(society, "A-101", age_minutes=30)

    escalated = sweep_once(timeout_minutes=10)
    assert str(sid) in escalated

    with scoped_session(society) as db:
        row = db.get(m.VisitorSession, sid)
        assert row.status == "escalated"          # no longer waiting forever
        assert row.resolved_by == "backup_contact"  # A-101 has a backup
        assert row.resolved_at is not None
        assert any("timeout" in e["action"] for e in row.decision_trace)

        esc = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == sid)
        ).scalars().first()
        assert esc is not None
        assert esc.escalated_to == "backup_contact"
        assert "did not reply" in esc.reason


def test_flat_without_backup_falls_back_to_the_guard(society):
    sid = _make_session(society, "A-103", age_minutes=30)

    sweep_once(timeout_minutes=10)

    with scoped_session(society) as db:
        row = db.get(m.VisitorSession, sid)
        assert row.status == "escalated"
        # No backup configured -> the guard's default policy, reported honestly.
        assert row.resolved_by == "guard_default"
        esc = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == sid)
        ).scalars().first()
        assert esc.escalated_to == "guard_default"


def test_recent_session_is_left_alone(society):
    sid = _make_session(society, "A-101", age_minutes=2)
    assert sweep_once(timeout_minutes=10) == []
    with scoped_session(society) as db:
        assert db.get(m.VisitorSession, sid).status == "awaiting_resident"


def test_a_reply_restarts_the_clock(society):
    """A resident asking a question must not be escalated out from under them."""
    sid = _make_session(society, "A-101", age_minutes=30)
    with system_session() as db:
        # Old session, but someone just spoke.
        db.add(m.ConversationLog(
            society_id=society, session_id=sid, turn_number=1,
            speaker="resident", message="who is it?",
            created_at=_now() - timedelta(minutes=1),
        ))
        db.flush()

    assert sweep_once(timeout_minutes=10) == []
    with scoped_session(society) as db:
        assert db.get(m.VisitorSession, sid).status == "awaiting_resident"


def test_stale_conversation_still_escalates(society):
    """The last turn is old too -> genuine silence -> escalate."""
    sid = _make_session(society, "A-101", age_minutes=60)
    with system_session() as db:
        db.add(m.ConversationLog(
            society_id=society, session_id=sid, turn_number=1,
            speaker="agent", message="Someone is at the gate",
            created_at=_now() - timedelta(minutes=45),
        ))
        db.flush()

    assert str(sid) in sweep_once(timeout_minutes=10)


def test_resolved_sessions_are_never_touched(society):
    """Only awaiting_resident is eligible; an approved visit stays approved."""
    sid = _make_session(society, "A-101", status="approved", age_minutes=999)
    assert sweep_once(timeout_minutes=10) == []
    with scoped_session(society) as db:
        assert db.get(m.VisitorSession, sid).status == "approved"


def test_sweep_is_idempotent(society):
    sid = _make_session(society, "A-101", age_minutes=30)
    first = sweep_once(timeout_minutes=10)
    second = sweep_once(timeout_minutes=10)
    assert str(sid) in first
    assert second == []  # already escalated; not escalated twice

    with scoped_session(society) as db:
        rows = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == sid)
        ).scalars().all()
        assert len(rows) == 1  # exactly one escalation record


def test_checkpointer_is_durable_not_in_memory():
    """
    Guards the regression that started this: with an in-memory checkpointer a
    restart silently strands every in-flight conversation.
    """
    from langgraph.checkpoint.memory import MemorySaver

    from backend.checkpointer import get_checkpointer

    cp = get_checkpointer()
    assert not isinstance(cp, MemorySaver), (
        "checkpointer fell back to MemorySaver — intercom conversations would not "
        "survive a restart"
    )
    assert type(cp).__name__ == "PostgresSaver"
