"""
Live Gate Agent decisions against seeded DB rules — the Phase 2 exit criterion.

This makes real Claude API calls, so it is opt-in: it only runs when
RUN_AGENT_TESTS is set (and needs ANTHROPIC_API_KEY). Kept out of the default
CI run to avoid per-PR API cost/flakiness.

    RUN_AGENT_TESTS=1 python -m pytest backend/tests/test_gate_agent.py -v
"""

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_AGENT_TESTS"),
    reason="set RUN_AGENT_TESTS=1 (and ANTHROPIC_API_KEY) to run live agent tests",
)


@pytest.fixture
def society():
    from backend import db_models as m
    from backend.deps import system_session

    with system_session() as db:
        soc = m.Society(name="AGENT-Test")
        db.add(soc)
        db.flush()
        db.add(m.Resident(
            society_id=soc.id, flat_number="A-101", name="Priya Sharma",
            standing_rules=[
                {"type": "always_allow", "match": "Raju"},
                {"type": "never_allow", "after": "21:00"},
            ],
        ))
        db.add(m.Visitor(
            society_id=soc.id, name="Raju", visitor_type="service",
            visit_count=12, typical_hours={"start": "09:00", "end": "18:00"},
        ))
        db.flush()
        sid = soc.id

    yield sid

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'AGENT-Test'"))


def test_gate_auto_approves_known_visitor(society):
    from backend.deps import scoped_session
    from backend.pipeline import handle_visitor_entry

    with scoped_session(society) as db:
        row = handle_visitor_entry(db, society, "Raju", "A-101", "service", "Plumbing repair")
        assert row.status == "auto_approved"
        assert any(e["agent"] == "gate" for e in row.decision_trace)


def test_gate_routes_unknown_guest_to_intercom(society):
    from backend.deps import scoped_session
    from backend.pipeline import handle_visitor_entry

    with scoped_session(society) as db:
        row = handle_visitor_entry(db, society, "Vikram Nair", "A-101", "guest", "Friend for dinner")
        assert row.status in ("awaiting_resident", "denied")  # routed onward, not auto-approved
