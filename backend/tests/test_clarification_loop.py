"""
The intercom clarification loop, end to end.

This is the flow LangGraph exists for: the graph pauses on interrupt(), the
resident asks a question instead of deciding, the guard answers, the agent
relays it, and only then does the resident decide. Each leg is a separate HTTP
request in production, so each leg here uses its own DB session — proving the
checkpointed graph resumes correctly with a fresh tenant-scoped context.

Real Claude calls (several per run), so it is opt-in:

    RUN_AGENT_TESTS=1 python -m pytest backend/tests/test_clarification_loop.py -v
"""

import os

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_AGENT_TESTS"),
    reason="set RUN_AGENT_TESTS=1 (and ANTHROPIC_API_KEY) to run live agent tests",
)


@pytest.fixture
def society():
    from backend import db_models as m
    from backend.deps import system_session

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'CLARIFY-Test'"))
        soc = m.Society(name="CLARIFY-Test")
        db.add(soc)
        db.flush()
        # No standing rules -> an unknown guest must reach the resident.
        db.add(m.Resident(society_id=soc.id, flat_number="A-101", name="Priya Sharma"))
        db.flush()
        sid = soc.id

    yield sid

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'CLARIFY-Test'"))


def test_resident_question_is_relayed_to_guard_then_resolved(society):
    from backend import db_models as m
    from backend.deps import scoped_session
    from backend.pipeline import handle_resident_reply, handle_visitor_entry

    # 1. Unknown guest arrives -> routed to the resident.
    with scoped_session(society) as db:
        row = handle_visitor_entry(
            db, society, "Vikram Nair", "A-101", "guest", "Friend visiting for dinner")
        assert row.status == "awaiting_resident"
        session_id = row.id

    # 2. Resident asks a question rather than deciding -> graph must NOT resolve.
    with scoped_session(society) as db:
        row = handle_resident_reply(
            db, db.get(m.VisitorSession, session_id), "Who is it? I'm not expecting anyone.")
        assert row.status == "awaiting_resident", "a question must not resolve the session"
        assert row.resolved_at is None

    # 3. Guard answers the question -> agent relays it back to the resident.
    with scoped_session(society) as db:
        row = handle_resident_reply(
            db, db.get(m.VisitorSession, session_id),
            "He says he's Vikram, your college friend, here for dinner")
        assert row.status == "awaiting_resident", "still waiting on the resident's decision"
        speakers = [t["speaker"] for t in row.conversation_history]
        assert "guard" in speakers, f"guard's answer should be in the transcript: {speakers}"

    # 4. Now the resident decides.
    with scoped_session(society) as db:
        row = handle_resident_reply(
            db, db.get(m.VisitorSession, session_id), "Oh yes! Please let him in, ALLOW")
        assert row.status == "approved"
        assert row.resolved_by == "resident"

    # The whole exchange is persisted for audit, in order.
    with scoped_session(society) as db:
        turns = db.execute(
            select(m.ConversationLog)
            .where(m.ConversationLog.session_id == session_id)
            .order_by(m.ConversationLog.turn_number)
        ).scalars().all()
        speakers = [t.speaker for t in turns]
        # agent notified, resident asked, guard answered, agent relayed, resident decided.
        assert speakers[0] == "agent"
        assert "guard" in speakers
        assert speakers.count("resident") >= 2
        assert len(turns) >= 5, speakers
