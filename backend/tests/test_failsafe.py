"""
Fail-toward-human: when an agent can't decide, a human does — and we never
auto-approve, never lose the visitor record.

Agent failures are forced by monkeypatching the agent entrypoints, so these run
offline and deterministically (no Claude API, no real timeouts).

    python -m pytest backend/tests/test_failsafe.py -v
"""

import pytest
from sqlalchemy import select, text

from backend import db_models as m
from backend import pipeline
from backend.deps import scoped_session, system_session


class Boom(Exception):
    """Stand-in for an LLM timeout / API error."""


@pytest.fixture
def society():
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'FS-Test'"))
        soc = m.Society(name="FS-Test")
        db.add(soc)
        db.flush()
        db.add(m.Resident(society_id=soc.id, flat_number="A-101", name="Priya Sharma"))
        db.flush()
        sid = soc.id
    yield sid
    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'FS-Test'"))


def test_gate_failure_escalates_to_guard_and_keeps_the_record(society, monkeypatch):
    monkeypatch.setattr(pipeline, "run_gate_agent",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("LLM timeout")))

    with scoped_session(society) as db:
        row = pipeline.handle_visitor_entry(
            db, society, "Vikram Nair", "A-101", "guest", "Friend for dinner")
        row_id = row.id
        assert row.status == "escalated"          # never auto_approved on error
        assert row.resolved_by == "guard_default"
        assert any(e["action"].startswith("agent_error") for e in row.decision_trace)

    # The session survived the failure (the request did not roll back), and the
    # escalation is visible to the admin audit.
    with scoped_session(society) as db:
        saved = db.get(m.VisitorSession, row_id)
        assert saved is not None, "visitor record must not be lost when an agent fails"
        assert saved.status == "escalated"
        esc = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == row_id)
        ).scalars().first()
        assert esc is not None
        assert "agent_failure" in esc.reason
        assert esc.escalated_to == "guard_default"


def test_delivery_failure_routes_to_resident_not_auto_approve(society, monkeypatch):
    # Gate hands off to delivery; delivery then fails.
    monkeypatch.setattr(pipeline, "run_gate_agent", lambda *a, **k: {
        "outcome": "routed_delivery", "message_history": [], "final_message": "", "session_id": "x",
    })
    monkeypatch.setattr(pipeline, "run_delivery_agent",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("API 529")))
    # Intercom still works -> the visitor should land in front of the resident.
    monkeypatch.setattr(pipeline, "start_intercom_session", lambda *a, **k: {
        "status": "awaiting_reply", "session_id": "x",
        "conversation_history": [{"speaker": "agent", "message": "Someone is here"}],
    })

    with scoped_session(society) as db:
        row = pipeline.handle_visitor_entry(
            db, society, "Rajesh", "A-101", "delivery", "Parcel from a local shop")
        assert row.status == "awaiting_resident"   # NOT auto_approved
        assert any(e["agent"] == "delivery" and e["action"].startswith("agent_error")
                   for e in row.decision_trace)


def test_intercom_start_failure_escalates_to_guard(society, monkeypatch):
    monkeypatch.setattr(pipeline, "run_gate_agent", lambda *a, **k: {
        "outcome": "routed_intercom", "message_history": [], "final_message": "", "session_id": "x",
    })
    monkeypatch.setattr(pipeline, "start_intercom_session",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("connection reset")))

    with scoped_session(society) as db:
        row = pipeline.handle_visitor_entry(
            db, society, "Vikram Nair", "A-101", "guest", "Dinner")
        assert row.status == "escalated"
        assert row.resolved_by == "guard_default"


def test_reply_failure_leaves_session_open(society, monkeypatch):
    with system_session() as db:
        sess = m.VisitorSession(
            society_id=society, visitor_name="Vikram", flat_number="A-101",
            purpose="guest", purpose_detail="Dinner", status="awaiting_resident",
        )
        db.add(sess)
        db.flush()
        sess_id = sess.id

    monkeypatch.setattr(pipeline, "intercom_reply",
                        lambda *a, **k: (_ for _ in ()).throw(Boom("LLM timeout")))

    with scoped_session(society) as db:
        row = db.get(m.VisitorSession, sess_id)
        out = pipeline.handle_resident_reply(db, row, "ALLOW")
        # Never resolve on a guess — the resident can try again.
        assert out.status == "awaiting_resident"
        assert out.resolved_at is None
        assert any(e["action"].startswith("agent_error") for e in out.decision_trace)
