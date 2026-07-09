"""
Live Delivery Triage Agent decisions against seeded DB data — the Phase 3 exit
criterion.

Makes real Claude API calls, so it is opt-in: it only runs when RUN_AGENT_TESTS
is set (and needs ANTHROPIC_API_KEY). Kept out of the default CI run to avoid
per-PR API cost/flakiness.

    RUN_AGENT_TESTS=1 python -m pytest backend/tests/test_delivery_agent.py -v
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
        soc = m.Society(name="DAGENT-Test")
        db.add(soc)
        db.flush()
        # Resident opts into daytime auto-logging; a known service should sail through.
        db.add(m.Resident(
            society_id=soc.id, flat_number="A-101", name="Priya Sharma",
            delivery_preferences={"auto_log_daytime": True, "notify_after_hours": True},
        ))
        db.add(m.Visitor(
            society_id=soc.id, name="Blinkit", visitor_type="delivery",
            is_known_service=True, visit_count=52,
            typical_hours={"start": "07:00", "end": "23:00"},
        ))
        db.flush()
        sid = soc.id

    yield sid

    with system_session() as db:
        db.execute(text("DELETE FROM societies WHERE name = 'DAGENT-Test'"))


def test_unknown_service_flags_anomaly_and_routes_intercom(society):
    from backend import db_models as m
    from backend.deps import scoped_session
    from backend.pipeline import handle_visitor_entry

    with scoped_session(society) as db:
        row = handle_visitor_entry(
            db, society, "Rajesh", "A-101", "delivery",
            "Parcel from an unnamed local shop",
        )
        # Delivery agent ran and could not auto-approve an unknown courier.
        assert any(e["agent"] == "delivery" for e in row.decision_trace)
        assert row.status in ("awaiting_resident", "escalated")

        # flag_anomaly persisted an escalation for this session (RLS-scoped).
        esc = db.execute(
            select(m.Escalation).where(m.Escalation.session_id == row.id)
        ).scalars().first()
        assert esc is not None
        assert "unknown_service" in esc.reason
